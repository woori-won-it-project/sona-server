"""수집 결과 검증 보고서.

data/raw/_report/full_report.json  검증 결과
data/raw/_report/all_rows.json     dispute_case 전체 (모든 컬럼)

사용 (레포 루트에서):
    python scripts/collector/report.py
"""
import json
import statistics
from collections import Counter
from datetime import datetime, timezone

from collector import CASE_SECTIONS, RAW_DIR, connect, load_env

REPORT_DIR = RAW_DIR / "_report"
SHORT_RAW_TEXT = 500


def length_stats(values: list[str | None]) -> dict:
    lengths = [len(v) for v in values if v]
    if not lengths:
        return {"count": 0, "null": len(values)}
    return {
        "count": len(lengths),
        "null": len(values) - len(lengths),
        "min": min(lengths),
        "median": statistics.median(lengths),
        "max": max(lengths),
    }


def main() -> None:
    conn = connect(load_env())
    cur = conn.execute("SELECT * FROM dispute_case ORDER BY doc_kind, source_key::int")
    cols = [d.name for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    jobs_cur = conn.execute("SELECT * FROM crawl_job ORDER BY id")
    job_cols = [d.name for d in jobs_cur.description]
    jobs = [dict(zip(job_cols, r)) for r in jobs_cur.fetchall()]

    case = [r for r in rows if r["doc_kind"] == "CASE"]
    std = [r for r in rows if r["doc_kind"] == "STANDARD"]

    # 건수
    counts = {
        "doc_kind": Counter(r["doc_kind"] for r in rows),
        "doc_kind_category": {k: Counter(r["category"] for r in rows if r["doc_kind"] == k) for k in ("CASE", "STANDARD")},
        "category": Counter(r["category"] for r in rows),
        "product_type": {k: Counter(r["product_type"] for r in rows if r["doc_kind"] == k) for k in ("CASE", "STANDARD")},
    }

    # CASE 구간 NULL
    case_null = {}
    for col, name in CASE_SECTIONS.items():
        items = [{"source_key": r["source_key"], "title": r["title"],
                  "notes": r["meta"].get("parse_notes")} for r in case if r[col] is None]
        case_null[col] = {"section": name, "count": len(items), "items": items}

    # STANDARD raw_text NULL / 짧음
    std_short = []
    for r in std:
        text = r["raw_text"]
        if text is None or len(text) < SHORT_RAW_TEXT:
            reason = r["meta"].get("raw_text_reason")
            if reason is None:
                reason = f"hwp5txt 결과가 {len(text)}자 (<표> {r['meta'].get('table_placeholders')}개)" if text else "raw_text NULL (사유 기록 없음)"
            std_short.append({"source_key": r["source_key"], "title": r["title"],
                              "raw_text_length": len(text or ""), "reason": reason,
                              "raw_text_source": r["meta"].get("raw_text_source")})

    # 첨부 실패, 목록 대비 첨부 수
    att_failures = [{"doc_kind": r["doc_kind"], "source_key": r["source_key"], "file_sn": a["file_sn"],
                     "name": a["name"], "error": a["download_error"]}
                    for r in rows for a in r["attachments"] if a.get("download_error")]
    list_mismatch = []
    for kind, doc_kind in (("case", "CASE"), ("standard", "STANDARD")):
        list_file = RAW_DIR / f"list_{kind}.json"
        if not list_file.exists():
            continue
        listed = json.loads(list_file.read_text(encoding="utf-8"))["items"]
        db = {r["source_key"]: r for r in rows if r["doc_kind"] == doc_kind}
        for item in listed:
            n_list = sum(len(v) for k, v in item.items() if k.startswith("attachments"))
            r = db.get(item["source_key"])
            n_db = len(r["attachments"]) if r else None
            if r is None or n_list != n_db:
                list_mismatch.append({"doc_kind": doc_kind, "source_key": item["source_key"],
                                      "list_attachments": n_list, "db_attachments": n_db})

    # DB 건수 vs HTML 파일 수
    files = {}
    for kind, doc_kind in (("case", "CASE"), ("standard", "STANDARD")):
        html_keys = {p.stem.split("_", 1)[1] for p in (RAW_DIR / kind).glob(f"{doc_kind}_*.html")}
        db_keys = {r["source_key"] for r in rows if r["doc_kind"] == doc_kind}
        list_file = RAW_DIR / f"list_{kind}.json"
        list_count = json.loads(list_file.read_text(encoding="utf-8"))["item_count"] if list_file.exists() else None
        att_files = [p for p in (RAW_DIR / kind / "attachments").glob("*") if not p.name.endswith(".manifest.json")]
        files[doc_kind] = {
            "list_count": list_count,
            "db_rows": len(db_keys),
            "html_files": len(html_keys),
            "match": len(db_keys) == len(html_keys) == (list_count or len(db_keys)) and db_keys == html_keys,
            "html_without_db": sorted(html_keys - db_keys),
            "db_without_html": sorted(db_keys - html_keys),
            "attachment_files": len(att_files),
            "attachment_entries_in_db": sum(len(r["attachments"]) for r in rows if r["doc_kind"] == doc_kind),
            "attachment_ext": Counter(p.suffix.lstrip(".") for p in att_files),
        }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_rows": len(rows),
        "crawl_jobs": jobs,
        "counts": counts,
        "case_section_null": case_null,
        "standard_raw_text_null_or_short": {"threshold": SHORT_RAW_TEXT, "count": len(std_short), "items": std_short},
        "attachment_download_failures": {"count": len(att_failures), "items": att_failures},
        "list_vs_db_attachment_mismatch": {"count": len(list_mismatch), "items": list_mismatch},
        "db_vs_files": files,
        "length_stats": {
            **{f"CASE.{col}": length_stats([r[col] for r in case]) for col in CASE_SECTIONS},
            "STANDARD.raw_text": length_stats([r["raw_text"] for r in std]),
        },
        "parse_notes": [{"doc_kind": r["doc_kind"], "source_key": r["source_key"], "notes": r["meta"]["parse_notes"]}
                        for r in rows if r["meta"].get("parse_notes")],
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "full_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (REPORT_DIR / "all_rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"rows={len(rows)} -> {REPORT_DIR / 'full_report.json'}, {REPORT_DIR / 'all_rows.json'}")


if __name__ == "__main__":
    main()
