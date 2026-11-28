"""검색 상위 개수(K) 비교 (이슈 #12). DB 는 읽기만, LLM 호출 없음 (질문 임베딩만, 캐시 재사용).

설정: 확정 스펙 k2v3_df10 (retrieval_concept_df.py 와 같은 코드)
    종류별 후보 50 (CASE·STANDARD / DECISION), C 0.7/0.3, DECISION_CLAUSE 제외,
    개념 태그(v3) 겹치는 자료 강제 포함 + 0.10, 문서 빈도 10% 초과 개념은 겹침 판단에서 제외.
    최종 개수만 바꿈: K = 10(7+3), 15(10+5), 20(14+6), 30(21+9)
정답: data/raw/_gold/label_sheet_final_v4.csv (relevance 1·2 = 정답), 대조군 retrieval_mix.CONTROLS
지표 (평가 질문만)
    recall@K        질문별 적중 / 정답 수 의 평균
    recall@K_capped 질문별 적중 / min(K, 정답 수) 의 평균 (기존 보고 0.836 은 이 정의)
    mrr@10, no_hit@K, new_hits = K 가 한 단계 늘며 새로 들어온 정답 수 (그리고 K=10 대비 누적)
    unlabeled_beyond10 = 상위 K 중 상위 10 에 없던 자료 가운데 정답표에 아예 없는 자료 수 (질문별)
결과: data/raw/_report/retrieval_eval_topk.json
질문 임베딩 캐시: data/raw/_report/topk_query_embeddings.json (텍스트·모델·차원이 같으면 재사용)

사용 (scripts/collector 에서): python retrieval_topk.py
"""
import hashlib
import json
from datetime import datetime, timezone

from collector import RAW_DIR, connect, load_env
from embedder import DEFAULT_DIMENSIONS, DEFAULT_MODEL, cost
from retrieval_concept_df import document_frequency, excluded_concepts, rank_concept
from retrieval_concept_v3 import BONUS, load_tag_sets
from retrieval_eval import CATEGORY, case_key, embed_texts, load_inputs, load_labeled_keys
from retrieval_mix import CONTROLS, GOLD_DIR, score_all

LABEL_V4 = GOLD_DIR / "label_sheet_final_v4.csv"
REPORT_FILE = RAW_DIR / "_report" / "retrieval_eval_topk.json"
EMBED_CACHE = RAW_DIR / "_report" / "topk_query_embeddings.json"
SPLITS = {10: (7, 3), 15: (10, 5), 20: (14, 6), 30: (21, 9)}
CONFIG = "k2v3_df10"
EXPECTED_K10 = {"recall@10_capped": 0.836, "mrr@10": 0.708, "no_hit": 1}


def _ekey(text: str) -> str:
    return hashlib.sha256(json.dumps([text, DEFAULT_MODEL, DEFAULT_DIMENSIONS], ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def cached_embed(client, texts: list[str]):
    """embed_texts 와 같은 결과, 캐시에 없는 텍스트만 API 호출."""
    cache = json.loads(EMBED_CACHE.read_text(encoding="utf-8")) if EMBED_CACHE.exists() else {}
    missing = [t for t in dict.fromkeys(texts) if _ekey(t) not in cache]
    tokens = 0
    if missing:
        vecs, tokens = embed_texts(client, missing)
        cache.update({_ekey(t): v for t, v in zip(missing, vecs)})
        EMBED_CACHE.parent.mkdir(parents=True, exist_ok=True)
        EMBED_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    cached_embed.stats = {"cached": len(texts) - len(missing), "embedded": len(missing)}
    return [cache[_ekey(t)] for t in texts], tokens


def df10_rankings(queries: list[dict]):
    """반환: ({K: {질문: 순위}}, 임베딩 토큰, 키, 제외 개념). 확정 스펙 df10 을 K 별로."""
    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")
    keys = {cid: case_key(k, s) for cid, k, s in conn.execute(
        "SELECT id, doc_kind, source_key FROM dispute_case WHERE category = %s", (CATEGORY,))}
    conn.close()
    tags = load_tag_sets({v: k for k, v in keys.items()})
    drop = set(excluded_concepts(document_frequency(tags["v3"]["doc"], write=False))[CONFIG])
    chunks, tokens, key = score_all(queries, embed=cached_embed)
    rankings = {k: {q["id"]: rank_concept(chunks[q["id"]], q["id"], tags["v3"], drop, BONUS, nb, nd)[0]
                    for q in queries} for k, (nb, nd) in SPLITS.items()}
    return rankings, tokens, key, sorted(drop)


def main() -> None:
    queries, gold = load_inputs(LABEL_V4)
    labeled = load_labeled_keys(LABEL_V4)
    control_ids = list(CONTROLS)
    eval_ids = [q["id"] for q in queries if q["id"] not in control_ids]
    if [q for q in eval_ids if not gold.get(q)]:
        raise SystemExit("정답 없는 평가 질문이 있습니다")
    rankings, tokens, key, drop = df10_rankings(queries)

    per_k, prev_hits = {}, {q: set() for q in eval_ids}
    top10 = {q: [x["case_key"] for x in rankings[10][q][:10]] for q in rankings[10]}
    for k in SPLITS:
        rows = {}
        for q in rankings[k]:
            top = [x["case_key"] for x in rankings[k][q][:k]]
            beyond = [c for c in top if c not in set(top10[q])]
            row = {"top": top, "beyond10": beyond,
                   "unlabeled_beyond10": [c for c in beyond if c not in labeled.get(q, set())]}
            if q in eval_ids:
                g = gold[q]
                hits = {c for c in top if c in g}
                first = next((i for i, c in enumerate(top[:10], 1) if c in g), None)
                row.update({"relevant": len(g), "hits": len(hits), "recall": len(hits) / len(g),
                            "recall_capped": len(hits) / min(k, len(g)), "rr@10": 1 / first if first else 0.0,
                            "new_hits": sorted(hits - prev_hits[q]),
                            "relevant_beyond10": [c for c in beyond if c in g]})
                prev_hits[q] = hits
            rows[q] = row
        ev = [rows[q] for q in eval_ids]
        n = len(ev)
        per_k[k] = {
            "split": "{}+{}".format(*SPLITS[k]),
            "summary": {
                "recall": round(sum(r["recall"] for r in ev) / n, 4),
                "recall_capped": round(sum(r["recall_capped"] for r in ev) / n, 4),
                "mrr@10": round(sum(r["rr@10"] for r in ev) / n, 4),
                "no_hit": sum(1 for r in ev if not r["hits"]),
                "no_hit_queries": [q for q in eval_ids if not rows[q]["hits"]],
                "hits_total": sum(r["hits"] for r in ev),
                "new_hits_vs_prev_k": sum(len(r["new_hits"]) for r in ev),
                "relevant_beyond10": sum(len(r["relevant_beyond10"]) for r in ev),
                "unlabeled_beyond10_eval": sum(len(r["unlabeled_beyond10"]) for r in ev),
                "unlabeled_beyond10_control": sum(len(rows[q]["unlabeled_beyond10"]) for q in control_ids),
            },
            "per_query": rows,
        }

    s10 = per_k[10]["summary"]
    check = {"expected": EXPECTED_K10,
             "actual": {"recall@10_capped": s10["recall_capped"], "recall@10": s10["recall"],
                        "mrr@10": s10["mrr@10"], "no_hit": s10["no_hit"]}}
    check["match"] = (round(s10["recall_capped"], 3) == EXPECTED_K10["recall@10_capped"]
                      and round(s10["mrr@10"], 3) == EXPECTED_K10["mrr@10"] and s10["no_hit"] == EXPECTED_K10["no_hit"])
    unl_table = {q: {k: len(per_k[k]["per_query"][q]["unlabeled_beyond10"]) for k in SPLITS if k > 10}
                 for q in [*eval_ids, *control_ids]}
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_file": str(LABEL_V4.relative_to(RAW_DIR.parent.parent)), "config": CONFIG,
        "splits": {k: list(v) for k, v in SPLITS.items()}, "bonus": BONUS, "excluded_concepts": drop,
        "eval_queries": eval_ids, "control_queries": control_ids,
        "k10_check": check,
        "embedding_usage": {"query_tokens": tokens, "cost_usd": cost(tokens, DEFAULT_MODEL),
                            **getattr(cached_embed, "stats", {})},
        "llm_usage": {"calls": 0},
        "summary_table": [{"K": k, "split": per_k[k]["split"], **per_k[k]["summary"]} for k in SPLITS],
        "unlabeled_beyond10_by_query": unl_table,
        "notes": [
            "recall_capped = 적중 / min(K, 정답 수). 정답이 K 보다 많은 질문에서 recall 상한이 1 이 되게 한 정의",
            "beyond10 = 상위 K 안에 있으나 K=10 상위 10 에는 없던 자료 (7:3 분할이라 순위 11~K 와 집합으로 같음; "
            "자료 순서는 점수순이라 일부는 10위 안쪽 자리에 끼어들 수 있음)",
            "라벨 없는 자료 = 그 질문의 정답표(v4)에 행이 없는 자료. 오답으로 계산되므로 많을수록 recall 이 과소 추정",
        ],
        "per_k": per_k,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert key not in text
    REPORT_FILE.write_text(text, encoding="utf-8")

    print(f"K=10 확인: {'일치' if check['match'] else '불일치'} {json.dumps(check['actual'], ensure_ascii=False)}")
    print(f"{'K':>4}{'분할':>7}{'R@K':>8}{'R@K(cap)':>10}{'무적중':>6}{'새정답':>6}{'11~K정답':>9}{'11~K무라벨':>11}")
    for k in SPLITS:
        s = per_k[k]["summary"]
        print(f"{k:>4}{per_k[k]['split']:>7}{s['recall']:>8.3f}{s['recall_capped']:>10.3f}{s['no_hit']:>6}"
              f"{s['new_hits_vs_prev_k']:>6}{s['relevant_beyond10']:>9}{s['unlabeled_beyond10_eval']:>11}")
    print("\n조항별 11~K 라벨 없는 자료 수 (15/20/30):")
    print("  " + "  ".join(f"{q}:{'/'.join(str(v) for v in d.values())}" for q, d in unl_table.items()))


if __name__ == "__main__":
    main()
