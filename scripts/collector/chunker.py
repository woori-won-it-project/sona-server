"""dispute_case -> case_chunk / case_tag 생성기 (임베딩은 하지 않음).

청크 종류
    CASE_BODY         CASE 1건 1청크 (chunk_index 0). [유형]/[제목]/[쟁점]/[처리결과]/[유의사항] 줄, NULL 인 줄은 생략
    STANDARD_SUMMARY  STANDARD 요지(summary) + meta.html_sections 중 heading 에 '심의 결과'가 들어간 구간. 둘 다 없으면 생략.
                      심의 결과가 요지를 포함하거나 요지와 거의 같으면(공백 무시) 요지는 뺀다
    STANDARD_SECTION  STANDARD raw_text 를 번호 단락(1. 2. ...)으로 분리. 번호가 2부터 시작하면 2번 앞의 글을 1번 단락으로
                      보고 heading 은 그 첫 줄(60자 이하일 때). 단락 끝의 본문 없는 '※ ...' 표시 줄은 제거.
                      제목 줄을 뺀 본문이 50자 미만인 단락은 청크로 만들지 않고 dispute_case.meta.table_only_sections 에 기록.
                      1500자 초과 단락은 먼저 '1) 2) ...' 소제목(1부터 순서대로, 60자 이하 줄)으로 나누고
                      heading 은 '상위 제목 > 소제목'. 소단락도 1500자를 넘거나 소제목이 없으면, 또는 번호 단락이 없으면
                      800자 단위로 나누고 앞뒤 100자 겹침
    모든 청크에서 유니코드 사용자 정의 영역 문자(U+E000–U+F8FF, U+F0000 이상)는 제거
    (BRIDGE 는 이 스크립트가 만들지도 지우지도 않는다)

저장 규칙
    (dispute_case_id, chunk_type, chunk_index) 기준 upsert. content_hash(sha256)가 바뀐 청크만 embedding·embedding_model 을
    NULL 로 되돌리고, 같으면 기존 임베딩 유지. 이번 실행에서 만들어지지 않은 기존 청크(같은 사례·같은 chunk_type)는 삭제.
    product_type 이 있으면 case_tag (PRODUCT, FSS) upsert.
    DB 저장 후 data/raw/_report/chunk_report.json 을 만든다 (DB 전체 기준 + 이번 실행 변경 수).

사용 (레포 루트에서):
    python scripts/collector/chunker.py
    python scripts/collector/chunker.py --dry-run --keys CASE:128,STANDARD:20
    python scripts/collector/chunker.py --kind standard --keys 19,20

옵션:
    --keys     처리할 사례 (쉼표 구분). 'CASE:128' / 'STANDARD:20' 형식, 또는 source_key 만 (--kind 가 없으면 양쪽 모두)
    --kind     case / standard 만 처리
    --dry-run  DB 저장 없이 만들어질 청크·태그만 출력
"""
import argparse
import difflib
import hashlib
import json
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone

from collector import RAW_DIR, connect, load_env

REPORT_FILE = RAW_DIR / "_report" / "chunk_report.json"
MANAGED_TYPES = ("CASE_BODY", "STANDARD_SUMMARY", "STANDARD_SECTION")  # BRIDGE 는 관리 대상 아님

SECTION_MAX = 1500      # 이 길이를 넘는 단락은 창 단위로 다시 나눈다
WINDOW = 800            # 창 크기
OVERLAP = 100           # 앞뒤 겹침
HEADING_MAX = 60        # 이 길이 이하인 번호 줄만 단락 제목으로 본다
HEADING_LINE = re.compile(r"^\s*(\d+)\.\s")
SUBHEADING_LINE = re.compile(r"^\s*(\d+)\)\s*\S")
PRIVATE_USE = re.compile("[\ue000-\uf8ff\U000f0000-\U0010ffff]")  # 사용자 정의 영역 (hwp 전용 기호 등)
TABLE_ONLY = re.compile(r"^\s*<표>\s*$")
SUMMARY_SECTION_MARK = "심의 결과"
SUMMARY_SIMILAR = 0.9   # 공백 제거 후 유사도가 이 이상이면 '거의 같다'
MIN_BODY = 50           # 제목 줄을 뺀 본문(공백 제외)이 이보다 짧은 단락은 청크로 만들지 않음 (본문이 표뿐인 단락)
NOTE_LABEL = re.compile(r"^\s*※")
NOTE_LABEL_MAX = 30     # 이 길이 이하이고 '.'으로 끝나지 않는 ※ 줄만 '본문 없는 표시 줄'로 본다 (예: '※ 관련 규정')

CASE_BODY_FIELDS = [("유형", "product_type"), ("제목", "title"), ("쟁점", "dispute_issue"),
                    ("처리결과", "decision_reason"), ("유의사항", "consumer_warning")]


# ---------------------------------------------------------------- 청크 만들기

def strip_pua(text: str | None) -> str | None:
    return PRIVATE_USE.sub("", text) if text else text


def strip_pua_row(row: dict) -> dict:
    """청크에 쓰는 텍스트에서 사용자 정의 영역 문자를 먼저 지운다 (자르기 전에 지워야 창 길이가 맞음)."""
    row = {k: strip_pua(v) if isinstance(v, str) else v for k, v in row.items()}
    meta = dict(row.get("meta") or {})
    if meta.get("html_sections"):
        meta["html_sections"] = [{**sec, "heading": strip_pua(sec.get("heading")), "text": strip_pua(sec.get("text"))}
                                 for sec in meta["html_sections"]]
    row["meta"] = meta
    return row


def chunk(chunk_type: str, index: int, content: str, heading: str | None = None) -> dict:
    content, heading = strip_pua(content), strip_pua(heading)
    return {
        "chunk_type": chunk_type,
        "chunk_index": index,
        "heading": heading[:300] if heading else None,
        "content": content,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "char_count": len(content),
    }


def case_body(row: dict) -> list[dict]:
    lines = [f"[{label}] {row[col].strip()}" for label, col in CASE_BODY_FIELDS if row.get(col) and row[col].strip()]
    return [chunk("CASE_BODY", 0, "\n".join(lines))] if lines else []


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def summary_covered(summary: str, decisions: list[str]) -> bool:
    """심의 결과 구간이 요지를 포함하거나 요지와 거의 같은지 (공백 무시)."""
    s = squash(summary)
    for d in map(squash, decisions):
        if s in d or difflib.SequenceMatcher(None, s, d).ratio() >= SUMMARY_SIMILAR:
            return True
    return False


def standard_summary(row: dict) -> list[dict]:
    summary = (row.get("summary") or "").strip()
    decisions = []
    for sec in (row.get("meta") or {}).get("html_sections") or []:
        heading, text = (sec.get("heading") or "").strip(), (sec.get("text") or "").strip()
        if SUMMARY_SECTION_MARK in heading and text:
            decisions.append((heading, text))
    parts = []
    if summary and not summary_covered(summary, [t for _, t in decisions]):
        parts.append(f"[요지] {summary}")
    parts += [f"[{h}] {t}" for h, t in decisions]
    return [chunk("STANDARD_SUMMARY", 0, "\n\n".join(parts))] if parts else []


def clean_lines(text: str) -> list[str]:
    """'<표>'만 있는 줄 제거, 연속된 빈 줄은 1줄로, 앞뒤 빈 줄 제거."""
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.rstrip()
        if TABLE_ONLY.match(line):
            continue
        if not line.strip():
            if out and out[-1] == "":
                continue
            line = ""
        out.append(line)
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return out


def scan_numbered(lines: list[str], start: int) -> list[tuple[str | None, list[str]]] | None:
    """start 부터 순서대로 올라가는 '번호. ' 줄(60자 이하)을 단락 제목으로 보고 나눈다.
    첫 항목은 제목 앞의 글(heading=None). 제목이 하나도 없으면 None."""
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    expected = start
    for line in lines:
        m = HEADING_LINE.match(line)
        if m and int(m.group(1)) == expected and len(line.strip()) <= HEADING_MAX:
            sections.append((line.strip(), [line]))
            expected += 1
        else:
            sections[-1][1].append(line)
    return sections if expected > start else None


def strip_note_labels(lines: list[str]) -> list[str]:
    """단락 끝에 본문 없이 남은 '※ 관련 규정' 같은 표시 줄(과 그 사이 빈 줄) 제거."""
    lines = list(lines)
    while lines:
        last = lines[-1].strip()
        if not last or (NOTE_LABEL.match(last) and len(last) <= NOTE_LABEL_MAX and not last.endswith(".")):
            lines.pop()
        else:
            break
    return lines


def split_numbered(lines: list[str]) -> tuple[list[tuple[str | None, str]], list[str]]:
    """번호 단락으로 나눈다. 반환: ([(heading, text)], 본문이 짧아 버린 단락 제목). 번호 단락이 없으면 ([], [])."""
    sections = scan_numbered(lines, 1)
    if sections is None:
        sections = scan_numbered(lines, 2)
        if sections is None:
            return [], []  # 번호 단락 없음
        # 2번부터 시작: 2번 앞의 글이 1번 단락, heading 은 첫 번째 비어 있지 않은 줄 (60자 이하일 때)
        pre = clean_lines("\n".join(sections[0][1]))
        first = pre[0].strip() if pre else ""
        sections[0] = (first if first and len(first) <= HEADING_MAX else None, sections[0][1])

    result, dropped = [], []
    for heading, body in sections:
        body_lines = strip_note_labels(clean_lines("\n".join(body)))
        if not body_lines:
            continue
        rest = body_lines[1:] if heading and body_lines[0].strip() == heading else body_lines
        if len(squash("\n".join(rest))) < MIN_BODY:
            if heading:
                dropped.append(heading)
            continue
        result.append((heading, "\n".join(body_lines)))
    return result, dropped


def split_subsections(heading: str | None, text: str) -> tuple[list[tuple[str | None, str]], list[str]]:
    """1500자 초과 단락을 '1) 2) ...' 소제목으로 나눈다. 소제목이 없으면 800자 창으로.
    반환: ([(heading, text)], 본문이 짧아 버린 소단락 제목)."""
    lines = text.split("\n")
    parts: list[tuple[str | None, list[str]]] = [(None, [])]
    expected = 1
    for line in lines:
        m = SUBHEADING_LINE.match(line)
        if m and int(m.group(1)) == expected and len(line.strip()) <= HEADING_MAX:
            parts.append((line.strip(), [line]))
            expected += 1
        else:
            parts[-1][1].append(line)
    if expected == 1:  # 소제목 없음
        return [(heading, w) for w in windows(text)], []

    pieces, dropped = [], []
    for sub, body in parts:
        body_lines = clean_lines("\n".join(body))
        if not body_lines:
            continue
        full = f"{heading} > {sub}" if heading and sub else (sub or heading)
        title = sub or heading  # 이 조각의 첫 줄이 제목이면 본문 길이에서 뺀다
        rest = body_lines[1:] if title and body_lines[0].strip() == title else body_lines
        if len(squash("\n".join(rest))) < MIN_BODY:
            if sub:                # 소제목만 남은 소단락은 기록
                dropped.append(full)
            continue                # 상위 제목 줄만 있는 머리 부분은 소단락 heading 에 이미 들어 있으므로 버림
        body_text = "\n".join(body_lines)
        if len(body_text) > SECTION_MAX:
            pieces += [(full, w) for w in windows(body_text)]
        else:
            pieces.append((full, body_text))
    return pieces, dropped


def windows(text: str) -> list[str]:
    if len(text) <= WINDOW:
        return [text]
    step = WINDOW - OVERLAP
    out, start = [], 0
    while True:
        out.append(text[start:start + WINDOW])
        if start + WINDOW >= len(text):
            return out
        start += step


def standard_sections(row: dict) -> tuple[list[dict], list[str]]:
    raw = row.get("raw_text")
    if not raw or not raw.strip():
        return [], []
    lines = clean_lines(raw)
    if not lines:
        return [], []
    sections, dropped = split_numbered(lines)
    pieces: list[tuple[str | None, str]] = []
    if sections:
        for heading, text in sections:
            if len(text) > SECTION_MAX:
                sub_pieces, sub_dropped = split_subsections(heading, text)
                pieces += sub_pieces
                dropped += sub_dropped
            else:
                pieces.append((heading, text))
    else:
        pieces = [(None, w) for w in windows("\n".join(strip_note_labels(lines)))]
    return [chunk("STANDARD_SECTION", i, text, heading) for i, (heading, text) in enumerate(pieces)], dropped


def build_chunks(row: dict) -> tuple[list[dict], list[str]]:
    """반환: (청크 목록, 본문이 짧아 청크로 만들지 않은 단락 제목 = meta.table_only_sections)."""
    row = strip_pua_row(row)
    if row["doc_kind"] == "CASE":
        return case_body(row), []
    if row["doc_kind"] == "STANDARD":
        sections, dropped = standard_sections(row)
        return standard_summary(row) + sections, dropped
    return [], []


# ---------------------------------------------------------------- DB 저장

UPSERT_CHUNK = """
INSERT INTO case_chunk (dispute_case_id, chunk_type, chunk_index, heading, content, content_hash, char_count)
VALUES (%(case_id)s, %(chunk_type)s, %(chunk_index)s, %(heading)s, %(content)s, %(content_hash)s, %(char_count)s)
ON CONFLICT (dispute_case_id, chunk_type, chunk_index) DO UPDATE SET
    heading = EXCLUDED.heading, content = EXCLUDED.content, char_count = EXCLUDED.char_count,
    embedding = CASE WHEN case_chunk.content_hash = EXCLUDED.content_hash THEN case_chunk.embedding END,
    embedding_model = CASE WHEN case_chunk.content_hash = EXCLUDED.content_hash THEN case_chunk.embedding_model END,
    content_hash = EXCLUDED.content_hash,
    updated_at = now()
WHERE case_chunk.content_hash IS DISTINCT FROM EXCLUDED.content_hash
   OR case_chunk.heading IS DISTINCT FROM EXCLUDED.heading
RETURNING (xmax = 0) AS inserted, (content_hash IS DISTINCT FROM %(old_hash)s) AS content_changed
"""

UPSERT_TAG = """
INSERT INTO case_tag (dispute_case_id, axis, value, source)
VALUES (%s, 'PRODUCT', %s, 'FSS')
ON CONFLICT (dispute_case_id, axis, value) DO NOTHING
"""


def save(conn, row: dict, chunks: list[dict], dropped: list[str], stats: Counter) -> None:
    from psycopg.types.json import Jsonb
    case_id = row["id"]
    with conn.transaction():
        if dropped:
            conn.execute("UPDATE dispute_case SET meta = coalesce(meta, '{}'::jsonb) || "
                         "jsonb_build_object('table_only_sections', %s::jsonb) WHERE id = %s", (Jsonb(dropped), case_id))
        else:
            conn.execute("UPDATE dispute_case SET meta = meta - 'table_only_sections' "
                         "WHERE id = %s AND meta ? 'table_only_sections'", (case_id,))
        old = {(r[0], r[1]): r[2] for r in conn.execute(
            "SELECT chunk_type, chunk_index, content_hash FROM case_chunk WHERE dispute_case_id = %s", (case_id,))}
        for c in chunks:
            old_hash = old.get((c["chunk_type"], c["chunk_index"]))
            res = conn.execute(UPSERT_CHUNK, dict(c, case_id=case_id, old_hash=old_hash)).fetchone()
            t = c["chunk_type"]
            if res is None:
                stats[(t, "unchanged")] += 1
            elif res[0]:
                stats[(t, "inserted")] += 1
            elif res[1]:
                stats[(t, "content_changed")] += 1
            else:
                stats[(t, "heading_only_changed")] += 1
        produced = Counter(c["chunk_type"] for c in chunks)
        for chunk_type in MANAGED_TYPES:
            deleted = conn.execute(
                "DELETE FROM case_chunk WHERE dispute_case_id = %s AND chunk_type = %s AND chunk_index >= %s",
                (case_id, chunk_type, produced[chunk_type])).rowcount
            if deleted:
                stats[(chunk_type, "deleted")] += deleted

        product = (row.get("product_type") or "").strip()
        stats[("case_tag", "deleted")] += conn.execute(
            "DELETE FROM case_tag WHERE dispute_case_id = %s AND axis = 'PRODUCT' AND source = 'FSS' AND value <> %s",
            (case_id, product)).rowcount
        if product:
            stats[("case_tag", "inserted")] += conn.execute(UPSERT_TAG, (case_id, product[:200])).rowcount


# ---------------------------------------------------------------- 보고서

def char_stats(values: list[int]) -> dict:
    if not values:
        return {"count": 0}
    return {"count": len(values), "min": min(values), "median": statistics.median(values), "max": max(values)}


def nest(stats: Counter) -> dict:
    out: dict[str, dict[str, int]] = {}
    for (group, what), n in sorted(stats.items()):
        out.setdefault(group, {})[what] = n
    return out


def write_report(conn, run_stats: Counter) -> dict:
    cur = conn.execute("""
        SELECT d.doc_kind, d.source_key, d.title, c.chunk_type, c.chunk_index, c.heading, c.char_count, c.content
        FROM case_chunk c JOIN dispute_case d ON d.id = c.dispute_case_id
        ORDER BY d.doc_kind, d.source_key::int, c.chunk_type, c.chunk_index""")
    cols = [d.name for d in cur.description]
    chunks = [dict(zip(cols, r)) for r in cur.fetchall()]

    by_type: dict[str, list[int]] = {}
    for c in chunks:
        by_type.setdefault(c["chunk_type"], []).append(c["char_count"])

    no_chunk = [dict(zip(("doc_kind", "source_key", "title"), r)) for r in conn.execute("""
        SELECT doc_kind, source_key, title FROM dispute_case d
        WHERE NOT EXISTS (SELECT 1 FROM case_chunk c WHERE c.dispute_case_id = d.id)
        ORDER BY doc_kind, source_key::int""")]

    tags = conn.execute("SELECT axis, source, count(*) FROM case_tag GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
    table_only = [{"doc_kind": r[0], "source_key": r[1], "sections": r[2]} for r in conn.execute("""
        SELECT doc_kind, source_key, meta->'table_only_sections' FROM dispute_case
        WHERE meta ? 'table_only_sections' ORDER BY doc_kind, source_key::int""")]
    no_heading = [r[0] for r in conn.execute("""
        SELECT d.source_key FROM dispute_case d WHERE d.doc_kind = 'STANDARD' AND NOT EXISTS (
            SELECT 1 FROM case_chunk c WHERE c.dispute_case_id = d.id
              AND c.chunk_type = 'STANDARD_SECTION' AND c.heading IS NOT NULL)
        ORDER BY d.source_key::int""")]

    def examples(doc_kind: str, key: str) -> list[dict]:
        return [{k: c[k] for k in ("chunk_type", "chunk_index", "heading", "char_count", "content")}
                for c in chunks if c["doc_kind"] == doc_kind and c["source_key"] == key]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "last_run_changes": nest(run_stats),
        "total_chunks": len(chunks),
        "chunk_type_count": {t: len(v) for t, v in sorted(by_type.items())},
        "char_count_by_type": {t: char_stats(v) for t, v in sorted(by_type.items())},
        "over_1500": [{k: c[k] for k in ("doc_kind", "source_key", "chunk_type", "chunk_index", "heading", "char_count")}
                      for c in chunks if c["char_count"] > SECTION_MAX],
        "dispute_case_without_chunks": no_chunk,
        "standard_without_section_heading": no_heading,
        "table_only_sections": table_only,
        "case_tag_count": {"total": sum(t[2] for t in tags),
                           "by_axis_source": [{"axis": a, "source": s, "count": n} for a, s, n in tags]},
        "examples": {"CASE_128": examples("CASE", "128"), "STANDARD_20": examples("STANDARD", "20"),
                     "STANDARD_2": examples("STANDARD", "2"), "STANDARD_16": examples("STANDARD", "16")},
    }
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


# ---------------------------------------------------------------- main

def parse_keys(keys: str | None, kind: str | None) -> list[tuple[str | None, str]]:
    result = []
    for k in (keys or "").split(","):
        k = k.strip()
        if not k:
            continue
        if ":" in k:
            doc_kind, key = k.split(":", 1)
            result.append((doc_kind.strip().upper(), key.strip()))
        else:
            result.append((kind.upper() if kind else None, k))
    return result


def load_rows(conn, kind: str | None, keys: list[tuple[str | None, str]]) -> list[dict]:
    cur = conn.execute("""
        SELECT id, doc_kind, source_key, title, product_type, summary, dispute_issue, decision_reason,
               consumer_warning, raw_text, meta
        FROM dispute_case ORDER BY doc_kind, source_key::int""")
    cols = [d.name for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    if kind:
        rows = [r for r in rows if r["doc_kind"] == kind.upper()]
    if keys:
        missing = [f"{dk or '*'}:{k}" for dk, k in keys
                   if not any(r["source_key"] == k and (dk is None or r["doc_kind"] == dk) for r in rows)]
        if missing:
            raise SystemExit(f"dispute_case 에 없는 key: {missing}")
        rows = [r for r in rows if any(r["source_key"] == k and (dk is None or r["doc_kind"] == dk) for dk, k in keys)]
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="dispute_case -> case_chunk / case_tag")
    parser.add_argument("--kind", choices=["case", "standard"])
    parser.add_argument("--keys", help="CASE:128,STANDARD:20 또는 source_key 목록 (쉼표 구분)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = connect(load_env())
    rows = load_rows(conn, args.kind, parse_keys(args.keys, args.kind))
    stats: Counter = Counter()
    type_count: Counter = Counter()
    for row in rows:
        chunks, dropped = build_chunks(row)
        type_count.update(c["chunk_type"] for c in chunks)
        label = f"[{row['doc_kind']} {row['source_key']}]"
        if args.dry_run:
            print(f"{label} {len(chunks)} chunks, tag PRODUCT={row.get('product_type')!r}, "
                  f"table_only_sections={dropped}")
            for c in chunks:
                print(f"  --- {c['chunk_type']} #{c['chunk_index']} ({c['char_count']}자) heading={c['heading']!r}")
                print("    " + c["content"].replace("\n", "\n    "))
            continue
        save(conn, row, chunks, dropped, stats)
        if not chunks:
            print(f"{label} chunk 없음", file=sys.stderr)

    print(f"cases={len(rows)} chunks={dict(type_count)}")
    if not args.dry_run:
        print(f"db: {json.dumps(nest(stats), ensure_ascii=False)}")
        report = write_report(conn, stats)
        print(f"report: {REPORT_FILE} (total_chunks={report['total_chunks']}, "
              f"over_1500={len(report['over_1500'])}, no_chunk={len(report['dispute_case_without_chunks'])}, "
              f"tags={report['case_tag_count']['total']})")
    conn.close()


if __name__ == "__main__":
    main()
