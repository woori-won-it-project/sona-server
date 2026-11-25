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
    DECISION_*        분쟁조정결정례. dispute_case.raw_text 를 decision.parse_document 로 다시 나눠 쓴다 (컬럼과 같은 결과)
      DECISION_SUMMARY  안건명 + 주문 + 결론, 1개
      DECISION_FACTS    신청취지 + 기초 사실. 1500자 초과면 번호 소제목으로 나누고, 그래도 길면 1200자 창 + 150자 겹침
      DECISION_JUDGMENT 위원회 판단. 번호 소제목((1), 가., 1. 등 본문에서 처음 나오는 단계, 번호가 1씩 올라가는 줄)으로
                        먼저 나누고, 1500자 초과 조각은 1200자 창 + 150자 겹침
      DECISION_CLAUSE   붙임(관련 약관). '제N조(' 줄과 '<붙임 N>' 줄마다 나누고, 초과 시 1200자 창 + 150자 겹침
      - 모든 DECISION 청크 content 맨 앞에 '[안건명] {안건명}\n', heading 은 섹션 이름 (소제목이 있으면 '섹션 > 소제목')
      - 150자 미만 조각은 다음 조각(마지막이면 앞 조각)에 붙인다
      - 당사자 주장은 청크로 만들지 않음. meta.disposition='각하' 인 행은 청크를 만들지 않음
      - 결론 안에 '<붙임 1>'·'<참고>' 줄이 있으면 (decision.py 가 붙임 제목으로 못 알아본 서식) 그 줄부터는 붙임으로 본다
      DECISION 을 처리하면 data/raw/_report/decision_chunk_report.json 도 만든다
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
    python scripts/collector/chunker.py --kind decision

옵션:
    --keys     처리할 사례 (쉼표 구분). 'CASE:128' / 'STANDARD:20' / 'DECISION:64814' 형식, 또는 source_key 만
               (--kind 가 없으면 모든 종류)
    --kind     case / standard / decision 만 처리
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

import decision as D
from collector import RAW_DIR, connect, load_env

REPORT_FILE = RAW_DIR / "_report" / "chunk_report.json"
DECISION_REPORT_FILE = RAW_DIR / "_report" / "decision_chunk_report.json"
DECISION_TYPES = ("DECISION_SUMMARY", "DECISION_FACTS", "DECISION_JUDGMENT", "DECISION_CLAUSE")
MANAGED_TYPES = ("CASE_BODY", "STANDARD_SUMMARY", "STANDARD_SECTION") + DECISION_TYPES  # BRIDGE 는 관리 대상 아님

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


# ---------------------------------------------------------------- 결정례 (DECISION)

D_LIMIT = 1500          # 청크 content(안건명 줄 포함) 최대 길이
D_WINDOW = 1200         # 창 크기
D_OVERLAP = 150         # 앞뒤 겹침
D_MIN_PIECE = 150       # 이보다 짧은 조각은 이웃 조각에 붙인다
D_AGENDA_MAX = 200
KOREAN_ORDER = "가나다라마바사아자차카타파하"
# 번호 소제목 단계. 나눌 글에서 처음 나오는 단계를 기준으로 쓴다
D_LEVELS = [
    ("(1)", re.compile(r"^\s*\((\d+)\)\s*\S")),
    ("가.", re.compile(r"^\s*([가-하])\.\s*\S")),
    ("1.", re.compile(r"^\s*(\d+)\.\s*\S")),
    ("1)", re.compile(r"^\s*(\d+)\)\s*\S")),
    ("(가)", re.compile(r"^\s*\(([가-하])\)\s*\S")),
]
ARTICLE_LINE = re.compile(r"^\s*제\s*\d+\s*조(?:\s*의\s*\d+)?\s*[(【\[〔<（「『]")
APPENDIX_LINE = re.compile(r"^\s*[<〈＜【\[]\s*(?:붙\s*임|참\s*고)[^>〉＞】\]]{0,15}[>〉＞】\]]\s*$")


def seq_value(raw: str) -> int:
    return KOREAN_ORDER.index(raw) + 1 if raw in KOREAN_ORDER else int(raw)


def split_by_numbering(text: str) -> tuple[list[tuple[str | None, str]], str | None]:
    """글에서 처음 나오는 번호 단계로, 번호가 1씩 올라가는 줄마다 나눈다.
    반환: ([(소제목 줄 | None, 조각)], 사용한 단계). 그 단계 소제목이 2개 미만이면 ([(None, text)], None)."""
    lines = text.split("\n")
    level = pattern = None
    for line in lines:
        for name, pat in D_LEVELS:
            if pat.match(line):
                level, pattern = name, pat
                break
        if level:
            break
    if not level:
        return [(None, text)], None
    parts: list[tuple[str | None, list[str]]] = [(None, [])]
    expected = None
    for line in lines:
        m = pattern.match(line)
        if m and (expected is None or seq_value(m.group(1)) == expected):
            expected = seq_value(m.group(1)) + 1
            parts.append((line.strip(), [line]))
        else:
            parts[-1][1].append(line)
    if len(parts) < 3:  # 소제목 1개뿐
        return [(None, text)], None
    return [(sub, "\n".join(body).strip()) for sub, body in parts if "\n".join(body).strip()], level


def split_articles(text: str) -> list[tuple[str | None, str]]:
    """'제N조(…)' 줄과 '<붙임 N>' 줄마다 나눈다 (약관이 여럿이면 조 번호가 다시 시작하므로 순서는 보지 않음)."""
    parts: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.split("\n"):
        if ARTICLE_LINE.match(line):
            parts.append((line.strip(), [line]))
        elif APPENDIX_LINE.match(line):
            parts.append((None, [line]))
        else:
            parts[-1][1].append(line)
    return [(sub, "\n".join(body).strip()) for sub, body in parts if "\n".join(body).strip()]


def merge_small(pieces: list[tuple[str | None, str]]) -> list[tuple[str | None, str]]:
    """D_MIN_PIECE 미만 조각을 다음 조각 앞에 붙인다 (마지막 조각이면 앞 조각 뒤에). 소제목은 먼저 나온 조각 것."""
    out: list[tuple[str | None, str]] = []
    carry: tuple[str | None, str] | None = None
    for sub, text in pieces:
        if carry:
            sub, text = (carry[0] or sub), carry[1] + "\n" + text
            carry = None
        if len(text) < D_MIN_PIECE:
            carry = (sub, text)
            continue
        out.append((sub, text))
    if carry:
        if out:
            out[-1] = (out[-1][0], out[-1][1] + "\n" + carry[1])
        else:
            out.append(carry)
    return out


def d_windows(text: str) -> list[str]:
    step = D_WINDOW - D_OVERLAP
    out, start = [], 0
    while True:
        out.append(text[start:start + D_WINDOW])
        if start + D_WINDOW >= len(text):
            return out
        start += step


def d_chunks(chunk_type: str, section: str, prefix: str, pieces: list[tuple[str | None, str]],
             stats: Counter) -> list[dict]:
    out = []
    for sub, text in merge_small(pieces):
        heading = f"{section} > {sub[:HEADING_MAX]}" if sub else section
        texts = [text] if len(prefix) + len(text) <= D_LIMIT else d_windows(text)
        if len(texts) > 1:
            stats[chunk_type] += 1
        out += [(heading, t) for t in texts]
    return [chunk(chunk_type, i, prefix + t, h) for i, (h, t) in enumerate(out)]


def decision_parts(row: dict) -> dict:
    """raw_text 를 decision.parse_document 로 다시 나눈다 (수집 때와 같은 함수). 컬럼과 다르면 mismatch 에 기록."""
    meta = row.get("meta") or {}
    doc = D.parse_document(row["raw_text"], meta.get("body_file_name"))
    by_key = {k: (v or "").strip() for k, v in doc["by_key"].items()}
    joined = "\n\n".join(by_key[k] for k in ("judgment", "conclusion") if by_key.get(k))
    mismatch = [col for col, val in (("summary", by_key.get("order")), ("complaint", by_key.get("facts")),
                                     ("decision_reason", joined))
                if strip_pua((row.get(col) or "").strip()) != strip_pua(val or "")]
    lines = by_key.get("conclusion", "").split("\n")
    at = next((i for i, line in enumerate(lines) if APPENDIX_LINE.match(line)), None)
    appendix_split = None
    if at is not None:
        appendix_split = lines[at].strip()
        by_key["appendix"] = "\n".join(x for x in ("\n".join(lines[at:]).strip(), by_key.get("appendix")) if x)
        by_key["conclusion"] = "\n".join(lines[:at]).strip()
    agenda = re.sub(r"\s+", " ", row.get("dispute_issue") or meta.get("agenda") or row["title"]).strip()
    return {"by_key": {k: strip_pua(v) for k, v in by_key.items()}, "agenda": agenda[:D_AGENDA_MAX],
            "mismatch": mismatch, "appendix_split": appendix_split}


def decision_chunks(row: dict, stats: Counter | None = None) -> tuple[list[dict], dict]:
    """반환: (청크, 이 행의 처리 정보 {skip_reason, judgment_level, appendix_split, mismatch, ...})."""
    stats = stats if stats is not None else Counter()
    meta = row.get("meta") or {}
    info: dict = {"disposition": meta.get("disposition")}
    if meta.get("disposition") == "각하":
        info["skip_reason"] = "각하 결정 (meta.disposition='각하') — 약관 해석 내용 없음"
        return [], info
    if not (row.get("raw_text") or "").strip():
        info["skip_reason"] = "raw_text 없음"
        return [], info
    parts = decision_parts(row)
    bk, prefix = parts["by_key"], f"[안건명] {parts['agenda']}\n"
    info.update(mismatch=parts["mismatch"], appendix_split=parts["appendix_split"])

    chunks: list[dict] = []
    summary = [f"[{label}] {bk[k]}" for label, k in (("주문", "order"), ("결론", "conclusion")) if bk.get(k)]
    if summary:
        body = "\n".join(summary)
        if len(prefix) + len(body) > D_LIMIT:  # 1개 원칙: 넘치면 뒷부분을 자른다 (보고서에 기록)
            info["summary_truncated"] = len(prefix) + len(body)
            body = body[:D_LIMIT - len(prefix)]
        chunks.append(chunk("DECISION_SUMMARY", 0, prefix + body, "요약(주문·결론)"))

    facts = "\n\n".join(x for x in ((f"[신청취지] {bk['claim']}" if bk.get("claim") else ""),
                                     (f"[기초 사실]\n{bk['facts']}" if bk.get("facts") else "")) if x)
    if facts:
        pieces = [(None, facts)] if len(prefix) + len(facts) <= D_LIMIT else split_by_numbering(facts)[0]
        chunks += d_chunks("DECISION_FACTS", "신청취지·기초 사실", prefix, pieces, stats)

    if bk.get("judgment"):
        pieces, level = split_by_numbering(bk["judgment"])
        info["judgment_level"] = level
        chunks += d_chunks("DECISION_JUDGMENT", "위원회 판단", prefix, pieces, stats)

    if bk.get("appendix"):
        chunks += d_chunks("DECISION_CLAUSE", "붙임(관련 약관)", prefix, split_articles(bk["appendix"]), stats)
    if not chunks:
        info["skip_reason"] = "청크로 만들 섹션 없음"
    return chunks, info


def build_chunks(row: dict) -> tuple[list[dict], list[str]]:
    """반환: (청크 목록, 본문이 짧아 청크로 만들지 않은 단락 제목 = meta.table_only_sections)."""
    row = strip_pua_row(row)
    if row["doc_kind"] == "CASE":
        return case_body(row), []
    if row["doc_kind"] == "STANDARD":
        sections, dropped = standard_sections(row)
        return standard_summary(row) + sections, dropped
    if row["doc_kind"] == "DECISION":
        return decision_chunks(row)[0], []
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
        ORDER BY d.doc_kind, split_part(d.source_key, '-', 1)::int, d.source_key, c.chunk_type, c.chunk_index""")
    cols = [d.name for d in cur.description]
    chunks = [dict(zip(cols, r)) for r in cur.fetchall()]

    by_type: dict[str, list[int]] = {}
    for c in chunks:
        by_type.setdefault(c["chunk_type"], []).append(c["char_count"])

    no_chunk = [dict(zip(("doc_kind", "source_key", "title"), r)) for r in conn.execute("""
        SELECT doc_kind, source_key, title FROM dispute_case d
        WHERE NOT EXISTS (SELECT 1 FROM case_chunk c WHERE c.dispute_case_id = d.id)
        ORDER BY doc_kind, split_part(source_key, '-', 1)::int, source_key""")]

    tags = conn.execute("SELECT axis, source, count(*) FROM case_tag GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
    table_only = [{"doc_kind": r[0], "source_key": r[1], "sections": r[2]} for r in conn.execute("""
        SELECT doc_kind, source_key, meta->'table_only_sections' FROM dispute_case
        WHERE meta ? 'table_only_sections' ORDER BY doc_kind, split_part(source_key, '-', 1)::int, source_key""")]
    no_heading = [r[0] for r in conn.execute("""
        SELECT d.source_key FROM dispute_case d WHERE d.doc_kind = 'STANDARD' AND NOT EXISTS (
            SELECT 1 FROM case_chunk c WHERE c.dispute_case_id = d.id
              AND c.chunk_type = 'STANDARD_SECTION' AND c.heading IS NOT NULL)
        ORDER BY split_part(d.source_key, '-', 1)::int""")]

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


def dist(values: list[int]) -> dict:
    if not values:
        return {"count": 0}
    s = sorted(values)
    at = lambda q: s[min(len(s) - 1, int(len(s) * q))]  # noqa: E731
    return {"count": len(s), "min": s[0], "p10": at(0.1), "median": statistics.median(s), "p90": at(0.9),
            "max": s[-1], "total_chars": sum(s)}


def write_decision_report(conn, run_stats: Counter, infos: dict[str, dict], window_split: Counter) -> dict:
    """DECISION 청크 보고서 (DB 기준 + 이번 실행에서 처리한 행의 정보)."""
    cur = conn.execute("""
        SELECT d.source_key, d.title, d.meta->>'disposition', c.chunk_type, c.chunk_index, c.heading, c.char_count,
               c.content
        FROM dispute_case d LEFT JOIN case_chunk c ON c.dispute_case_id = d.id
        WHERE d.doc_kind = 'DECISION'
        ORDER BY split_part(d.source_key, '-', 1)::int, d.source_key, c.chunk_type, c.chunk_index""")
    rows = cur.fetchall()
    chunks = [r for r in rows if r[3]]
    by_type: dict[str, list[int]] = {t: [] for t in DECISION_TYPES}
    for r in chunks:
        by_type.setdefault(r[3], []).append(r[6])
    keys = list(dict.fromkeys(r[0] for r in rows))
    row_info = {r[0]: (r[1], r[2]) for r in rows}
    with_chunks = {r[0] for r in chunks}
    per_row_type = Counter((r[0], r[3]) for r in chunks)

    def example(key: str) -> list[dict]:
        return [{"chunk_type": r[3], "chunk_index": r[4], "heading": r[5], "char_count": r[6], "content": r[7]}
                for r in chunks if r[0] == key]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rules": {"limit": D_LIMIT, "window": D_WINDOW, "overlap": D_OVERLAP, "merge_pieces_under": D_MIN_PIECE,
                  "content_prefix": "[안건명] {안건명}\\n",
                  "not_chunked": ["당사자 주장", "meta.disposition='각하' 인 행 전체"]},
        "last_run_changes": nest(run_stats),
        "rows": {"decision_rows": len(keys), "with_chunks": len(with_chunks),
                 "without_chunks": len(keys) - len(with_chunks)},
        "total_chunks": len(chunks),
        "chunk_type_count": {t: len(v) for t, v in by_type.items()},
        "rows_having_type": {t: len({k for (k, tt) in per_row_type if tt == t}) for t in DECISION_TYPES},
        "char_count_by_type": {t: dist(v) for t, v in by_type.items()},
        "char_count_all": dist([r[6] for r in chunks]),
        "over_1500_count": sum(1 for r in chunks if r[6] > D_LIMIT),
        "over_1500": [{"source_key": r[0], "chunk_type": r[3], "chunk_index": r[4], "char_count": r[6]}
                      for r in chunks if r[6] > D_LIMIT],
        "rows_without_chunks": [{"source_key": k, "title": row_info[k][0], "disposition": row_info[k][1],
                                 "reason": (infos.get(k) or {}).get("skip_reason", "(이번 실행에서 처리 안 함)")}
                                for k in keys if k not in with_chunks],
        "rows_without_judgment_chunk": sorted(k for k in with_chunks if not per_row_type[(k, "DECISION_JUDGMENT")]),
        "rows_without_facts_chunk": sorted(k for k in with_chunks if not per_row_type[(k, "DECISION_FACTS")]),
        "judgment_split_level": dict(Counter(i.get("judgment_level") or "(소제목 2개 미만 → 나누지 않음)"
                                             for i in infos.values() if "judgment_level" in i)),
        "window_split_pieces_by_type": dict(window_split),
        "appendix_split_from_conclusion": [{"source_key": k, "line": i["appendix_split"]}
                                           for k, i in infos.items() if i.get("appendix_split")],
        "summary_truncated": [{"source_key": k, "chars_before": i["summary_truncated"]}
                              for k, i in infos.items() if i.get("summary_truncated")],
        "column_mismatch": [{"source_key": k, "columns": i["mismatch"]} for k, i in infos.items() if i.get("mismatch")],
        "disposition_count": dict(Counter(row_info[k][1] or "(없음)" for k in keys)),
        "examples": {"DECISION_64814": example("64814"), "DECISION_64799": example("64799")},
    }
    DECISION_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    DECISION_REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
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
        SELECT id, doc_kind, source_key, title, product_type, summary, complaint, dispute_issue, decision_reason,
               consumer_warning, raw_text, meta
        FROM dispute_case ORDER BY doc_kind, split_part(source_key, '-', 1)::int, source_key""")
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
    parser.add_argument("--kind", choices=["case", "standard", "decision"])
    parser.add_argument("--keys", help="CASE:128,STANDARD:20,DECISION:64814 또는 source_key 목록 (쉼표 구분)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = connect(load_env())
    rows = load_rows(conn, args.kind, parse_keys(args.keys, args.kind))
    stats: Counter = Counter()
    type_count: Counter = Counter()
    decision_infos: dict[str, dict] = {}
    window_split: Counter = Counter()  # 창으로 나눈 조각 수 (chunk_type 별)
    for row in rows:
        if row["doc_kind"] == "DECISION":
            chunks, info = decision_chunks(strip_pua_row(row), window_split)
            decision_infos[row["source_key"]], dropped = info, []
        else:
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
            print(f"{label} chunk 없음 {decision_infos.get(row['source_key'], {}).get('skip_reason', '')}",
                  file=sys.stderr)

    print(f"cases={len(rows)} chunks={dict(type_count)}")
    if not args.dry_run:
        print(f"db: {json.dumps(nest(stats), ensure_ascii=False)}")
        report = write_report(conn, stats)
        print(f"report: {REPORT_FILE} (total_chunks={report['total_chunks']}, "
              f"over_1500={len(report['over_1500'])}, no_chunk={len(report['dispute_case_without_chunks'])}, "
              f"tags={report['case_tag_count']['total']})")
        if decision_infos:
            d = write_decision_report(conn, stats, decision_infos, window_split)
            print(f"report: {DECISION_REPORT_FILE} (chunks={d['chunk_type_count']}, "
                  f"over_1500={d['over_1500_count']}, rows_without_chunks={len(d['rows_without_chunks'])})")
    conn.close()


if __name__ == "__main__":
    main()
