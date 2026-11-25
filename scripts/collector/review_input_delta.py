"""label_delta*.csv 채점용 입력 만들기 (DB 는 읽기만 한다).

입력: label_delta*.csv (retrieval_eval.py --decision / --mix / --mix2 결과), data/raw/_gold/gold_queries.json
출력: 질문별 리스트
    {query_id, clause_ref, clause_text, candidates: [
        {case_key, doc_kind, title, delta_ranks {rank_A, rank_B, rank_C}, source_config, current_rank, case_score,
         결정례(D):           agenda(안건명), order(주문), disposition, product_type, decision_date,
                              facts (기초 사실 앞 600자), judgment (위원회 판단 앞 1500자)
         사례·해결기준(C·S):  dispute_issue, decision_reason (앞 1500자), product_type
         best_chunk {chunk_type, chunk_index, heading, content (앞 800자), chunk_score, vector_sim, keyword}}]}

source_config: --configs 순서의 설정 중 지금 DB 기준으로 이 자료를 상위 10 에 올린 설정 (순위가 가장 좋은 것, 같으면 앞 순서).
    상위 10 에 올린 설정이 없으면 순위가 가장 좋은 설정을 쓰고 not_in_top10_now=true.
best_chunk: 그 설정이 검색 대상으로 쓴 청크 중 이 자료의 청크 점수(0.7×(1-거리)+0.3×word_similarity)가 가장 높은 청크
    (설정 f·h 에서 결정례는 DECISION_SUMMARY 만). 설정 정의는 retrieval_mix.build_rankings.
위원회 판단은 raw_text 를 decision.parse_document 로 다시 나눠 쓴다 (decision_reason 컬럼에는 결론이 붙어 있으므로).
질문 임베딩 때문에 OpenAI 를 한 번 부른다 (키 값은 출력하지 않음).
(2026-11-25 첫 실행의 review_input_delta.json 은 설정 b 고정 형식: delta_rank_b/c, case_score_b, current_rank_b)

사용 (레포 루트에서):
    python scripts/collector/review_input_delta.py --delta data/raw/_gold/label_delta2.csv \\
        --out data/raw/_gold/review_input_delta2.json --configs e,f,a
"""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import decision as D
from collector import connect, load_env
from embedder import DEFAULT_MODEL, cost
from retrieval_eval import GOLD_DIR, QUERIES_FILE, case_key
from retrieval_mix import W_KW, W_VEC, build_rankings, score_all

FACTS_MAX, JUDGMENT_MAX, CHUNK_MAX = 600, 1500, 800
KIND_BY_PREFIX = {"C": "CASE", "S": "STANDARD", "D": "DECISION"}


def split_key(k: str) -> tuple[str, str]:
    return KIND_BY_PREFIX[k[0]], k[1:]


def load_documents(conn, keys: set[str]) -> dict[str, dict]:
    docs = {}
    for doc_kind, source_key, title, summary, complaint, dispute_issue, decision_reason, product_type, raw_text, meta \
            in conn.execute("""SELECT doc_kind, source_key, title, summary, complaint, dispute_issue, decision_reason,
                                      product_type, raw_text, meta FROM dispute_case"""):
        k = case_key(doc_kind, source_key)
        if k not in keys:
            continue
        meta = meta or {}
        if doc_kind == "DECISION":
            judgment = D.parse_document(raw_text, meta.get("body_file_name"))["by_key"].get("judgment") or ""
            docs[k] = {"doc_kind": doc_kind, "title": title, "agenda": dispute_issue, "order": summary,
                       "disposition": meta.get("disposition"), "product_type": product_type,
                       "decision_date": meta.get("decision_date"),
                       "facts": (complaint or "")[:FACTS_MAX] or None, "judgment": judgment[:JUDGMENT_MAX] or None}
        else:
            docs[k] = {"doc_kind": doc_kind, "title": title, "dispute_issue": dispute_issue,
                       "decision_reason": (decision_reason or "")[:JUDGMENT_MAX] or None, "product_type": product_type}
    return docs


def build_review(delta_file: Path, out_file: Path, configs: list[str], ranker=None,
                 label_name: str = "label_sheet_final_v2.csv") -> dict:
    """ranker(qid, chunks) -> ({설정: 순위}, {설정: 청크}). 없으면 retrieval_mix.build_rankings (a·b·d·e·f·g·h)."""
    queries = {q["id"]: q for q in json.loads(QUERIES_FILE.read_text(encoding="utf-8"))["queries"]}
    with delta_file.open(encoding="utf-8-sig", newline="") as f:
        delta = list(csv.DictReader(f))
    by_query: dict[str, list[dict]] = {}
    for row in delta:
        by_query.setdefault(row["query_id"], []).append(row)
    qids = sorted(by_query, key=list(queries).index)

    chunks, tokens, key = score_all([queries[q] for q in qids])
    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")  # DB 쓰기 금지
    wanted = {r["case_key"] for r in delta}
    docs = load_documents(conn, wanted)
    missing = sorted(wanted - set(docs))
    if missing:
        raise SystemExit(f"DB 에 없는 자료: {missing}")

    out, problems, source_count = [], [], {}
    for qid in qids:
        rankings, pools = ranker(qid, chunks[qid]) if ranker else build_rankings(chunks[qid], qid, {})
        picks = {}
        for row in by_query[qid]:
            k = row["case_key"]
            ranks = []
            for order, n in enumerate(configs):
                pos = next((i for i, x in enumerate(rankings[n], 1) if x["case_key"] == k), None)
                if pos:
                    ranks.append((pos, order, n))
            in_top = [r for r in ranks if r[0] <= 10]
            chosen = min(in_top or ranks, default=None)
            if chosen is None:
                problems.append(f"{qid}:{k} 어느 설정의 후보에도 없음")
            elif not in_top:
                problems.append(f"{qid}:{k} 지금은 상위 10 밖 ({chosen[2]} {chosen[0]}위)")
            picks[k] = chosen
        rep = {}
        for k, chosen in picks.items():
            if not chosen:
                continue
            n = chosen[2]
            cs = [c for c in pools[n] if case_key(c["doc_kind"], c["source_key"]) == k]
            if cs:
                rep[k] = max(cs, key=lambda c: (W_VEC * (1 - c["distance"]) + W_KW * c["keyword"], -c["id"]))
        contents = {r[0]: r[1:] for r in conn.execute(
            "SELECT id, chunk_index, heading, content FROM case_chunk WHERE id = ANY(%s)",
            ([c["id"] for c in rep.values()],))} if rep else {}

        candidates = []
        for row in by_query[qid]:
            k = row["case_key"]
            chosen, best = picks[k], rep.get(k)
            source = chosen[2] if chosen else None
            source_count[source] = source_count.get(source, 0) + 1
            ranked = rankings[source] if source else []
            entry = next((x for x in ranked if x["case_key"] == k), None)
            idx, heading, content = contents[best["id"]] if best else (None, None, None)
            candidates.append({
                "case_key": k, "doc_kind": docs[k]["doc_kind"], "title": docs[k]["title"],
                "delta_ranks": {c: (int(row[c]) if row[c] else None) for c in ("rank_A", "rank_B", "rank_C")},
                "source_config": source, "current_rank": chosen[0] if chosen else None,
                "not_in_top10_now": bool(chosen and chosen[0] > 10),
                "case_score": round(entry["score"], 4) if entry else None,
                **{f: v for f, v in docs[k].items() if f not in ("doc_kind", "title")},
                "best_chunk": {
                    "chunk_type": best["chunk_type"], "chunk_index": idx, "heading": heading,
                    "content": content[:CHUNK_MAX],
                    "chunk_score": round(W_VEC * (1 - best["distance"]) + W_KW * best["keyword"], 4),
                    "vector_sim": round(1 - best["distance"], 4), "keyword": round(best["keyword"], 4),
                } if best else None,
            })
        out.append({"query_id": qid, "clause_ref": queries[qid].get("clause_ref"),
                     "clause_text": queries[qid]["query_text"], "candidates": candidates})
    conn.close()

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": delta_file.name, "configs_preference": configs,
        "config_note": "C 0.7/0.3, category=보험, DECISION_CLAUSE 제외. 설정 정의는 retrieval_mix.build_rankings",
        "limits": {"facts": FACTS_MAX, "judgment_or_decision_reason": JUDGMENT_MAX, "best_chunk_content": CHUNK_MAX},
        "label_guide": f"relevance 2 = 매우 관련, 1 = 관련, 0 = 무관 ({label_name} 와 같은 기준)",
        "counts": {"queries": len(out), "candidates": sum(len(x["candidates"]) for x in out),
                   "by_source_config": source_count},
        "problems": problems,
        "usage": {"embedding_tokens": tokens, "embedding_cost_usd": cost(tokens, DEFAULT_MODEL)},
        "queries": out,
    }
    text = json.dumps(data, ensure_ascii=False, indent=2)
    assert key not in text
    out_file.write_text(text, encoding="utf-8")
    print(f"{out_file}: 질문 {len(out)}개, 후보 {data['counts']['candidates']}개, 설정별 {source_count}, "
          f"문제 {len(problems)}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="label_delta 채점 입력 만들기 (DB 읽기 전용)")
    parser.add_argument("--delta", default=str(GOLD_DIR / "label_delta.csv"))
    parser.add_argument("--out", default=str(GOLD_DIR / "review_input_delta.json"))
    parser.add_argument("--configs", default="b", help="best_chunk 를 고를 설정 (선호 순, 쉼표 구분: a,b,d,e,f,g,h)")
    a = parser.parse_args()
    build_review(Path(a.delta), Path(a.out), [c.strip() for c in a.configs.split(",") if c.strip()])


if __name__ == "__main__":
    main()
