"""정답셋(gold_label) 라벨링용 후보표 만들기. DB 는 읽기만 한다.

입력: data/raw/_gold/gold_queries.json  ({"queries": [{id, clause_ref, query_text, hint_cases, ...}]})
처리: query_text 를 embedder.py 와 같은 모델로 임베딩 → search_probe.py 의 A / B / C 방식으로 사례 상위 10개씩
      (category='보험') → 후보 = A ∪ B ∪ C 상위 10 ∪ hint_cases
      한 방식만 쓰면 그 방식에 유리한 정답셋이 되므로 세 방식 후보를 모두 합친다.
      A 는 청크 순위이므로, 사례가 처음 나오는 순서로 사례 순위를 매긴다.
출력: data/raw/_gold/label_sheet.csv  (UTF-8 BOM, 엑셀용)
      컬럼 query_id, clause_ref, case_key(C5/S20), title, rank_A, rank_B, rank_C, is_hint, relevance(빈칸)
      query_id(파일 순서) → rank_C 순 (rank_C 없으면 뒤로)
      data/raw/_report/gold_candidates.json  실행 요약 (쿼리 수, 쿼리별 후보 수, 토큰, 비용)

사용 (레포 루트에서):
    python scripts/collector/gold_candidates.py
"""
import argparse
import csv
import json
from datetime import datetime, timezone

from collector import RAW_DIR, connect, load_env
from embedder import DEFAULT_DIMENSIONS, DEFAULT_MODEL, cost, masker, openai_key, to_vector_literal
from search_probe import CANDIDATE_CHUNKS, CATEGORY, SCORE_SQL, W_KEYWORD, W_VECTOR, rank_methods

GOLD_DIR = RAW_DIR / "_gold"
QUERIES_FILE = GOLD_DIR / "gold_queries.json"
SHEET_FILE = GOLD_DIR / "label_sheet.csv"
REPORT_FILE = RAW_DIR / "_report" / "gold_candidates.json"
TOP_K = 10
EMBED_BATCH = 100
COLUMNS = ["query_id", "clause_ref", "case_key", "title", "rank_A", "rank_B", "rank_C", "is_hint", "relevance"]
PREFIX = {"CASE": "C", "STANDARD": "S"}


def case_key(doc_kind: str, source_key: str) -> str:
    return f"{PREFIX[doc_kind]}{source_key}"


def case_ranks(methods: dict) -> dict[str, dict[str, int]]:
    """방식별 사례 순위 상위 TOP_K: {"A": {case_key: rank}, "B": ..., "C": ...}."""
    a, seen = {}, set()
    for row in methods["A_vector_chunk"]:  # 청크 순위 → 사례 첫 등장 순서
        k = case_key(*row["_key"])
        if k not in seen:
            seen.add(k)
            a[k] = len(seen)
            if len(seen) == TOP_K:
                break
    b = {case_key(*r["_key"]): r["rank"] for r in methods["B_case_grouped"][:TOP_K]}
    c = {case_key(*r["_key"]): r["rank"] for r in methods["C_case_hybrid"][:TOP_K]}
    return {"A": a, "B": b, "C": c}


def embed_all(client, texts: list[str]) -> tuple[list[list[float]], int]:
    vectors, tokens = [], 0
    for i in range(0, len(texts), EMBED_BATCH):
        res = client.embeddings.create(model=DEFAULT_MODEL, input=texts[i:i + EMBED_BATCH],
                                       dimensions=DEFAULT_DIMENSIONS)
        vectors += [d.embedding for d in sorted(res.data, key=lambda d: d.index)]
        tokens += res.usage.total_tokens
    return vectors, tokens


def main() -> None:
    argparse.ArgumentParser(description="정답셋 라벨링 후보표 생성 (DB 읽기 전용)").parse_args()
    import openai

    queries = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))["queries"]

    key = openai_key()
    if not key:
        raise SystemExit("OPENAI_API_KEY 가 .env 와 환경 변수에 없습니다")
    mask = masker(key)
    client = openai.OpenAI(api_key=key, max_retries=3, timeout=60)
    try:
        vectors, tokens = embed_all(client, [q["query_text"] for q in queries])
    except openai.APIError as e:
        raise SystemExit(mask(f"임베딩 실패: {type(e).__name__} {getattr(e, 'status_code', '')}")) from None

    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")  # DB 쓰기 금지 (autocommit 문장에도 적용)
    titles = {case_key(dk, sk): t for dk, sk, t in conn.execute(
        "SELECT doc_kind, source_key, title FROM dispute_case WHERE doc_kind IN ('CASE', 'STANDARD')")}
    categories = {case_key(dk, sk): c for dk, sk, c in conn.execute(
        "SELECT doc_kind, source_key, category FROM dispute_case WHERE doc_kind IN ('CASE', 'STANDARD')")}

    rows, summary = [], []
    for q, vec in zip(queries, vectors):
        cur = conn.execute(SCORE_SQL, {"vec": to_vector_literal(vec), "query": q["query_text"], "category": CATEGORY})
        cols = [d.name for d in cur.description]
        chunks = [dict(zip(cols, r)) for r in cur.fetchall()]
        for c in chunks:
            c["distance"], c["keyword"] = float(c["distance"]), float(c["keyword"])
        ranks = case_ranks(rank_methods(chunks))

        hints = list(dict.fromkeys(q.get("hint_cases") or []))
        unknown = [h for h in hints if h not in titles]
        candidates = list(dict.fromkeys([*ranks["C"], *ranks["B"], *ranks["A"], *[h for h in hints if h in titles]]))
        q_rows = [{
            "query_id": q["id"], "clause_ref": q.get("clause_ref", ""), "case_key": k, "title": titles[k],
            "rank_A": ranks["A"].get(k, ""), "rank_B": ranks["B"].get(k, ""), "rank_C": ranks["C"].get(k, ""),
            "is_hint": 1 if k in hints else 0, "relevance": "",
        } for k in candidates]
        big = TOP_K + 1
        q_rows.sort(key=lambda r: (r["rank_C"] or big, r["rank_B"] or big, r["rank_A"] or big, r["case_key"]))
        rows += q_rows

        hint_only = [h for h in hints if h in titles and all(h not in ranks[m] for m in "ABC")]
        summary.append({
            "query_id": q["id"], "control": bool(q.get("control")), "candidates": len(q_rows),
            "from_search": len(set(ranks["A"]) | set(ranks["B"]) | set(ranks["C"])),
            "hints": len(hints), "hints_found_by_search": len(hints) - len(hint_only) - len(unknown),
            "hints_only": hint_only, "hints_not_in_db": unknown,
            "hints_outside_category": [h for h in hints if h in categories and categories[h] != CATEGORY],
            "overlap_ABC_top10": len(set(ranks["A"]) & set(ranks["B"]) & set(ranks["C"])),
        })
    conn.close()

    SHEET_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SHEET_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": DEFAULT_MODEL, "dimensions": DEFAULT_DIMENSIONS, "category": CATEGORY, "top_k_per_method": TOP_K,
        "method_params": {"candidate_chunks_for_B_C": CANDIDATE_CHUNKS, "weights": {"vector": W_VECTOR,
                                                                                   "keyword": W_KEYWORD}},
        "queries": len(queries), "sheet_rows": len(rows),
        "tokens": tokens, "cost_usd": cost(tokens, DEFAULT_MODEL),
        "sheet_file": str(SHEET_FILE.relative_to(RAW_DIR.parent.parent)),
        "per_query": summary,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert key not in text
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(text, encoding="utf-8")

    print(f"queries={len(queries)} rows={len(rows)} tokens={tokens:,} cost=${report['cost_usd']:.6f}")
    for s in summary:
        print(f"  {s['query_id']}: 후보 {s['candidates']} (검색 {s['from_search']}, 힌트 {s['hints']}, "
              f"힌트만 {len(s['hints_only'])}{', 대조군' if s['control'] else ''})")
    print(f"sheet: {SHEET_FILE}\nreport: {REPORT_FILE}")


if __name__ == "__main__":
    main()
