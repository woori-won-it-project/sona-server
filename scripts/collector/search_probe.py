"""검색 방식 비교 (category='보험').

A. 벡터만      청크 단위 코사인 거리 상위 N
B. 사례 묶기   상위 50 청크 → dispute_case 별로 가장 가까운 청크 하나 → 사례 상위 N
C. B+하이브리드 B 의 후보 사례마다 점수 = 0.7 × (1 - 최소 거리) + 0.3 × 키워드 점수
               키워드 점수 = 사례의 모든 청크에 대한 pg_trgm word_similarity(질문, content) 최댓값
               대표 청크 = 사례 안에서 0.7 × 청크 유사도 + 0.3 × 청크 키워드 점수 가 가장 큰 청크

추적 사례 순위: A 는 그 사례 청크가 처음 나오는 청크 순위, B·C 는 사례 순위. 20위 안에 없으면 "20위 밖".
거리는 HNSW 근사가 아니라 대상 청크 전체를 정확히 계산한다 (청크 수가 적음).

사용 (레포 루트에서):
    python scripts/collector/search_probe.py
결과: data/raw/_report/search_probe.json (키 값은 넣지 않음)
"""
import argparse
import json
from datetime import datetime, timezone

from collector import RAW_DIR, connect, load_env
from embedder import DEFAULT_DIMENSIONS, DEFAULT_MODEL, cost, masker, openai_key, to_vector_literal

REPORT_FILE = RAW_DIR / "_report" / "search_probe.json"
CATEGORY = "보험"
TOP_N = 5
TRACK_LIMIT = 20
CANDIDATE_CHUNKS = 50
W_VECTOR, W_KEYWORD = 0.7, 0.3

PROBES = [
    {"query": "수술의 정의에 해당하지 않는 시술은 수술보험금을 지급하지 않습니다",
     "track": [("CASE", k) for k in ("61", "104", "141", "142", "143", "25")]},
    {"query": "체외충격파 치료는 연간 횟수 제한이 있습니다",
     "track": [("STANDARD", "20")], "rep_check": {"case": ("STANDARD", "20"), "heading_contains": "심의 결과"}},
    {"query": "타인의 사망을 보험금 지급사유로 하는 계약은 피보험자의 서면 동의가 필요합니다",
     "track": [("CASE", "35"), ("STANDARD", "15")]},
]

SCORE_SQL = """
SELECT c.id, c.dispute_case_id, d.doc_kind, d.source_key, d.title, c.chunk_type, c.chunk_index, c.heading,
       c.embedding <=> %(vec)s::vector AS distance,
       word_similarity(%(query)s, c.content) AS keyword
FROM case_chunk c JOIN dispute_case d ON d.id = c.dispute_case_id
WHERE d.category = %(category)s AND c.embedding IS NOT NULL
"""


def chunk_view(c: dict) -> dict:
    return {"chunk_type": c["chunk_type"], "chunk_index": c["chunk_index"], "heading": c["heading"]}


def case_view(c: dict) -> dict:
    return {"doc_kind": c["doc_kind"], "source_key": c["source_key"], "title": c["title"]}


def rank_methods(chunks: list[dict]) -> dict:
    by_dist = sorted(chunks, key=lambda c: (c["distance"], c["id"]))

    # A. 청크 단위
    a = [{"rank": i, "score": round(c["distance"], 4), "score_name": "distance", **case_view(c),
          "chunk": chunk_view(c), "_key": (c["doc_kind"], c["source_key"])}
         for i, c in enumerate(by_dist, 1)]

    # B. 상위 50 청크 → 사례별 최근접 청크
    best: dict[int, dict] = {}
    for c in by_dist[:CANDIDATE_CHUNKS]:
        best.setdefault(c["dispute_case_id"], c)
    b_sorted = sorted(best.values(), key=lambda c: (c["distance"], c["id"]))
    b = [{"rank": i, "score": round(c["distance"], 4), "score_name": "distance", **case_view(c),
          "chunk": chunk_view(c), "_key": (c["doc_kind"], c["source_key"])}
         for i, c in enumerate(b_sorted, 1)]

    # C. B 의 후보 사례에 하이브리드 점수
    by_case: dict[int, list[dict]] = {}
    for c in chunks:
        by_case.setdefault(c["dispute_case_id"], []).append(c)
    c_rows = []
    for case_id, nearest in best.items():
        case_chunks = by_case[case_id]
        sim = 1 - min(x["distance"] for x in case_chunks)
        kw_chunk = max(case_chunks, key=lambda x: (x["keyword"], -x["id"]))
        kw = kw_chunk["keyword"]
        rep = max(case_chunks, key=lambda x: (W_VECTOR * (1 - x["distance"]) + W_KEYWORD * x["keyword"], -x["id"]))
        c_rows.append({"score": W_VECTOR * sim + W_KEYWORD * kw, "vector_sim": sim, "keyword": kw,
                       "rep": rep, "kw_chunk": kw_chunk, "nearest": nearest})
    c_rows.sort(key=lambda r: (-r["score"], r["rep"]["id"]))
    c = [{"rank": i, "score": round(r["score"], 4), "score_name": "0.7*vector_sim+0.3*keyword",
          "vector_sim": round(r["vector_sim"], 4), "keyword": round(r["keyword"], 4), **case_view(r["rep"]),
          "chunk": chunk_view(r["rep"]), "nearest_chunk": chunk_view(r["nearest"]),
          "keyword_chunk": chunk_view(r["kw_chunk"]), "_key": (r["rep"]["doc_kind"], r["rep"]["source_key"])}
         for i, r in enumerate(c_rows, 1)]
    return {"A_vector_chunk": a, "B_case_grouped": b, "C_case_hybrid": c}


def tracked_rank(rows: list[dict], key: tuple[str, str]) -> dict:
    for r in rows:
        if r["_key"] == key:
            if r["rank"] > TRACK_LIMIT:
                break
            return {"rank": r["rank"], "chunk": r["chunk"]}
    return {"rank": f"{TRACK_LIMIT}위 밖", "chunk": None}


def strip(rows: list[dict], n: int) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "_key"} for r in rows[:n]]


def main() -> None:
    argparse.ArgumentParser(description="검색 방식 비교 (category='보험')").parse_args()
    import openai

    key = openai_key()
    if not key:
        raise SystemExit("OPENAI_API_KEY 가 .env 와 환경 변수에 없습니다")
    mask = masker(key)
    client = openai.OpenAI(api_key=key, max_retries=2, timeout=60)
    try:
        res = client.embeddings.create(model=DEFAULT_MODEL, input=[p["query"] for p in PROBES],
                                       dimensions=DEFAULT_DIMENSIONS)
    except openai.APIError as e:
        raise SystemExit(mask(f"임베딩 실패: {type(e).__name__} {getattr(e, 'status_code', '')}")) from None
    vectors = [d.embedding for d in sorted(res.data, key=lambda d: d.index)]

    conn = connect(load_env())
    results = []
    for probe, vec in zip(PROBES, vectors):
        cur = conn.execute(SCORE_SQL, {"vec": to_vector_literal(vec), "query": probe["query"], "category": CATEGORY})
        cols = [d.name for d in cur.description]
        chunks = [dict(zip(cols, r)) for r in cur.fetchall()]
        for c in chunks:
            c["distance"], c["keyword"] = float(c["distance"]), float(c["keyword"])
        methods = rank_methods(chunks)

        tracked = {}
        for doc_kind, source_key in probe["track"]:
            entry = {m: tracked_rank(rows, (doc_kind, source_key)) for m, rows in methods.items()}
            check = probe.get("rep_check")
            if check and check["case"] == (doc_kind, source_key):
                for m in entry.values():
                    h = (m["chunk"] or {}).get("heading") or ""
                    m["rep_is_target_section"] = check["heading_contains"] in h if m["chunk"] else None
            tracked[f"{doc_kind} {source_key}"] = entry

        results.append({"query": probe["query"], "candidate_chunks": len(chunks),
                        "top": {m: strip(rows, TOP_N) for m, rows in methods.items()}, "tracked": tracked})
    conn.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": DEFAULT_MODEL, "category": CATEGORY, "top_n": TOP_N, "track_limit": TRACK_LIMIT,
        "candidate_chunks_for_B_C": CANDIDATE_CHUNKS, "weights": {"vector": W_VECTOR, "keyword": W_KEYWORD},
        "query_tokens": res.usage.total_tokens, "query_cost_usd": cost(res.usage.total_tokens, DEFAULT_MODEL),
        "notes": [
            "A 의 추적 순위는 그 사례 청크가 처음 나오는 청크 순위",
            "B·C 후보는 벡터 상위 50 청크에 든 사례만 (여기 없으면 C 에서도 20위 밖)",
            "C 대표 청크 = 사례 안에서 0.7*청크 유사도 + 0.3*청크 키워드 점수가 가장 큰 청크",
            "거리는 정확 계산 (HNSW 근사 아님)",
        ],
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    assert key not in text
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(text, encoding="utf-8")

    for r in results:
        print(f"\n=== {r['query']}")
        for m, rows in r["top"].items():
            print(f"  [{m}]")
            for x in rows:
                extra = f" (vec {x['vector_sim']}, kw {x['keyword']})" if "keyword" in x else ""
                print(f"    {x['rank']}. {x['score']}{extra} {x['chunk']['chunk_type']} "
                      f"{x['chunk']['heading'] or ''} | {x['doc_kind']} {x['source_key']} {x['title'][:40]}")
        print("  [추적]")
        for case, entry in r["tracked"].items():
            parts = []
            for m, v in entry.items():
                s = f"{m[0]}={v['rank']}"
                if "rep_is_target_section" in v:
                    s += f"(심의결과 대표:{v['rep_is_target_section']})"
                parts.append(s)
            print(f"    {case}: " + ", ".join(parts))
    print(f"\nreport: {REPORT_FILE}")


if __name__ == "__main__":
    main()
