"""결정례를 섞는 방식 비교 (retrieval_eval.py --mix 가 부른다). DB 는 읽기만 한다.

정답: data/raw/_gold/label_sheet_final_v2.csv (relevance 1·2 = 정답, 0 또는 표에 없는 자료 = 오답)
공통: C 0.7/0.3, category='보험', 자료 단위 상위 10, 후보 = (설정별로 거른) 청크 중 벡터 상위 50 청크에 든 자료.
      DECISION_CLAUSE 청크는 모든 설정에서 제외.

설정
    a) CASE + STANDARD 만 (기준선)
    b) + DECISION. 자료 점수 = 0.7 × (1 - 자료 최소 거리) + 0.3 × 자료 최대 word_similarity  (retrieval_eval.rank_cases)
    d) 자리 나누기: b 점수로 CASE·STANDARD 상위 7 + DECISION 상위 3 을 뽑아 점수순으로 합침.
       한쪽 후보가 모자라면 다른 쪽으로 10 까지 채움. 11위부터는 남은 후보를 점수순
    e) 점수 보정: 청크 점수 = 0.7 × (1 - 거리) + 0.3 × word_similarity, 자료 점수 = 상위 2개 청크 점수 평균
       (자료의 청크가 1개면 그 점수). 후보는 b 와 같음
    f) 대표 청크만: DECISION 은 DECISION_SUMMARY 청크만 검색 대상, 나머지는 b 와 같음 (후보 청크 50 유지)

지표: recall@5, recall@10, MRR@10, nDCG@10, 질문별 첫 정답 순위(전체 후보 기준), 대조군 1위 점수,
      상위 10 중 결정례 수, 상위 10 중 라벨 없는 자료 수
label_delta2.csv: 어느 설정이든 상위 10 에 든 라벨 없는 자료 (label_sheet_final_v2.csv 와 같은 컬럼.
      rank_A = a 순위, rank_B = b 순위, rank_C = d·e·f 중 가장 좋은 순위 (설정별 순위는 보고서에), relevance 빈칸)
결과: data/raw/_report/retrieval_eval_mix.json
"""
import csv
import json
from datetime import datetime, timezone

from collector import RAW_DIR, connect, load_env
from embedder import DEFAULT_MODEL, cost, masker, openai_key
from retrieval_eval import (BASE_KINDS, CANDIDATE_CHUNKS, CATEGORY, EXPANSION_WEIGHT, GOLD_DIR, LABEL_COLUMNS, TOP_K,
                            embed_texts, evaluate, load_inputs, load_labeled_keys, rank_cases, score_chunks)

LABEL_V2 = GOLD_DIR / "label_sheet_final_v2.csv"
DELTA2_FILE = GOLD_DIR / "label_delta2.csv"
REPORT_FILE = RAW_DIR / "_report" / "retrieval_eval_mix.json"
FOCUS = ["G02", "G06", "G13", "G14", "G16"]
SPLIT_BASE, SPLIT_DECISION = 7, 3
W_VEC, W_KW = EXPANSION_WEIGHT  # 0.7 / 0.3


def is_decision(r: dict) -> bool:
    return r["case_key"].startswith("D")


def rank_split(ranked: list[dict], fills: list[str], qid: str) -> list[dict]:
    """d) b 순위에서 CASE·STANDARD 7 + DECISION 3 (모자라면 다른 쪽으로 채움) → 점수순, 나머지는 뒤에 점수순."""
    base = [r for r in ranked if not is_decision(r)]
    dec = [r for r in ranked if is_decision(r)]
    nb, nd = min(SPLIT_BASE, len(base)), min(SPLIT_DECISION, len(dec))
    if nb < SPLIT_BASE:
        nd = min(len(dec), TOP_K - nb)
    if nd < SPLIT_DECISION:
        nb = min(len(base), TOP_K - nd)
    if (nb, nd) != (SPLIT_BASE, SPLIT_DECISION):
        fills.append(f"{qid}: CASE·STANDARD {nb} + DECISION {nd} (후보 {len(base)}/{len(dec)})")
    top = base[:nb] + dec[:nd]
    chosen = {r["case_key"] for r in top}
    order = lambda r: (-r["score"], r["_tie"])  # noqa: E731
    return sorted(top, key=order) + sorted((r for r in ranked if r["case_key"] not in chosen), key=order)


def rank_top2(chunks: list[dict]) -> list[dict]:
    """e) 후보는 rank_cases 와 같게, 자료 점수 = 청크 점수(0.7×유사도 + 0.3×키워드) 상위 2개 평균."""
    base = rank_cases(chunks, W_VEC, W_KW)  # 후보·제목·대표 청크 id
    by_key: dict[str, list[float]] = {}
    for c in chunks:
        key = ("C" if c["doc_kind"] == "CASE" else "S" if c["doc_kind"] == "STANDARD" else "D") + c["source_key"]
        by_key.setdefault(key, []).append(W_VEC * (1 - c["distance"]) + W_KW * c["keyword"])
    out = []
    for r in base:
        top = sorted(by_key[r["case_key"]], reverse=True)[:2]
        out.append({**r, "score": sum(top) / len(top), "chunks_used": len(top)})
    out.sort(key=lambda r: (-r["score"], r["_tie"]))
    return out


def eval_mix() -> None:
    import openai

    queries, gold = load_inputs(LABEL_V2)
    labeled = load_labeled_keys(LABEL_V2)
    eval_ids = [q["id"] for q in queries if gold.get(q["id"])]
    control_ids = [q["id"] for q in queries if not gold.get(q["id"])]

    key = openai_key()
    if not key:
        raise SystemExit("OPENAI_API_KEY 가 .env 와 환경 변수에 없습니다")
    mask = masker(key)
    client = openai.OpenAI(api_key=key, max_retries=3, timeout=120)
    try:
        vecs, tokens = embed_texts(client, [q["query_text"] for q in queries])
    except openai.APIError as e:
        raise SystemExit(mask(f"API 실패: {type(e).__name__} {getattr(e, 'status_code', '')}")) from None

    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")  # DB 쓰기 금지
    chunks = {q["id"]: [c for c in score_chunks(conn, q["query_text"], v) if c["chunk_type"] != "DECISION_CLAUSE"]
              for q, v in zip(queries, vecs)}
    conn.close()

    only_base = lambda cs: [c for c in cs if c["doc_kind"] in BASE_KINDS]  # noqa: E731
    summary_only = lambda cs: [c for c in cs if c["doc_kind"] != "DECISION" or c["chunk_type"] == "DECISION_SUMMARY"]  # noqa: E731
    fills: list[str] = []
    rankings = {
        "a": {q: rank_cases(only_base(cs), W_VEC, W_KW) for q, cs in chunks.items()},
        "b": {q: rank_cases(cs, W_VEC, W_KW) for q, cs in chunks.items()},
    }
    rankings["d"] = {q: rank_split(r, fills, q) for q, r in rankings["b"].items()}
    rankings["e"] = {q: rank_top2(cs) for q, cs in chunks.items()}
    rankings["f"] = {q: rank_cases(summary_only(cs), W_VEC, W_KW) for q, cs in chunks.items()}
    desc = {
        "a": "CASE + STANDARD 만 (기준선)",
        "b": "+ DECISION, 자료 점수 = 청크 최고점",
        "d": f"자리 나누기 CASE·STANDARD {SPLIT_BASE} + DECISION {SPLIT_DECISION}",
        "e": "점수 보정: 상위 2개 청크 점수 평균",
        "f": "DECISION 은 DECISION_SUMMARY 만",
    }

    results = []
    for name in ("a", "b", "d", "e", "f"):
        rk = rankings[name]
        r = evaluate(f"{name}) {desc[name]}", desc[name], rk, gold, control_ids)
        unl = {q: [x["case_key"] for x in rk[q][:TOP_K] if x["case_key"] not in labeled.get(q, set())] for q in rk}
        dec = {q: [x["case_key"] for x in rk[q][:TOP_K] if is_decision(x)] for q in rk}
        rel_dec = {q: [k for k in dec[q] if gold.get(q, {}).get(k)] for q in eval_ids}
        r["summary"].update({
            "decision_in_top10_eval": sum(len(dec[q]) for q in eval_ids),
            "relevant_decision_in_top10_eval": sum(len(v) for v in rel_dec.values()),
            "unlabeled_in_top10_eval": sum(len(unl[q]) for q in eval_ids),
            "unlabeled_in_top10_control": sum(len(unl[q]) for q in control_ids),
            "control_top1": {q: r["controls"][q]["top1_score"] for q in control_ids},
        })
        r["unlabeled_top10"] = {q: v for q, v in unl.items() if v}
        r["decision_top10"] = {q: v for q, v in dec.items() if v}
        for q in control_ids:
            r["controls"][q]["top10"] = [{"rank": i, "case_key": x["case_key"], "title": x["title"],
                                          "score": round(x["score"], 4)} for i, x in enumerate(rk[q][:TOP_K], 1)]
        results.append(r)

    names = ["a", "b", "d", "e", "f"]
    first_rank = {q: {n: res["first_relevant_rank"][q] for n, res in zip(names, results)} for q in eval_ids}

    # label_delta2.csv: 어느 설정이든 상위 10 에 든 라벨 없는 자료
    qmap = {q["id"]: q for q in queries}
    delta: dict[tuple[str, str], dict] = {}
    for n in names:
        for qid, ranked in rankings[n].items():
            for i, x in enumerate(ranked[:TOP_K], 1):
                if x["case_key"] in labeled.get(qid, set()):
                    continue
                row = delta.setdefault((qid, x["case_key"]), {"query_id": qid, "case_key": x["case_key"],
                                                               "title": x["title"], "ranks": {}})
                row["ranks"][n] = i
    delta_rows = []
    for (qid, k), d in sorted(delta.items(), key=lambda kv: ([q["id"] for q in queries].index(kv[0][0]),
                                                              min(kv[1]["ranks"].values()), kv[0][1])):
        best_def = min((d["ranks"][n] for n in ("d", "e", "f") if n in d["ranks"]), default="")
        delta_rows.append({"query_id": qid, "clause_ref": qmap[qid].get("clause_ref", ""), "case_key": k,
                           "title": d["title"], "rank_A": d["ranks"].get("a", ""), "rank_B": d["ranks"].get("b", ""),
                           "rank_C": best_def, "is_hint": 1 if k in (qmap[qid].get("hint_cases") or []) else 0,
                           "relevance": "", "_ranks": d["ranks"]})
    if delta_rows:
        with DELTA2_FILE.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LABEL_COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(delta_rows)

    emb_cost = cost(tokens, DEFAULT_MODEL)
    keys = ("recall@5", "recall@10", "mrr@10", "ndcg@10", "no_hit@10", "decision_in_top10_eval",
            "relevant_decision_in_top10_eval", "unlabeled_in_top10_eval", "unlabeled_in_top10_control",
            "control_top1_mean", "eval_top1_mean")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_file": str(LABEL_V2.relative_to(RAW_DIR.parent.parent)),
        "category": CATEGORY, "top_k": TOP_K, "candidate_chunks": CANDIDATE_CHUNKS,
        "weights": {"vector": W_VEC, "keyword": W_KW}, "excluded_chunk_type": "DECISION_CLAUSE",
        "configs": desc,
        "eval_queries": eval_ids, "control_queries": control_ids,
        "relevant_count": {q: {"total": len(gold[q]), "decision": sum(1 for k in gold[q] if k.startswith("D"))}
                           for q in eval_ids},
        "usage": {"embedding_tokens": tokens, "embedding_cost_usd": emb_cost},
        "notes": [
            "정답 수(분모)에 결정례 정답이 포함되므로 a 는 결정례 정답을 찾을 수 없어 recall 상한이 1 보다 낮다",
            "질문 목록·임베딩은 모든 설정이 같고, 정답이 하나라도 있는 질문만 평가 (나머지는 대조군)",
            "e 의 자료 점수는 청크별 0.7×유사도+0.3×키워드 의 상위 2개 평균. b 는 유사도·키워드를 자료 안에서 따로 최대값을 잡는다",
            f"label_delta2.csv rank_C = d·e·f 중 가장 좋은 순위. 설정별 순위는 label_delta2 항목에",
        ],
        "summary_table": [{"config": r["name"], **{k: r["summary"][k] for k in keys}} for r in results],
        "focus_first_relevant_rank": {q: first_rank.get(q) for q in FOCUS},
        "first_relevant_rank": first_rank,
        "split_fills_d": fills,
        "label_delta2": {"file": str(DELTA2_FILE.relative_to(RAW_DIR.parent.parent)) if delta_rows else None,
                         "rows": len(delta_rows),
                         "items": [{k: v for k, v in r.items() if k in ("query_id", "case_key", "title", "_ranks")}
                                   for r in delta_rows]},
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert key not in text
    REPORT_FILE.write_text(text, encoding="utf-8")

    print(f"{'설정':<4}{'R@5':>7}{'R@10':>7}{'MRR':>7}{'nDCG':>7}{'무적중':>5}{'D수':>5}{'D정답':>5}{'무라벨':>5}"
          f"{'대조1위':>8}{'평가1위':>8}")
    for r in results:
        s = r["summary"]
        print(f"{r['name'][:2]:<4}{s['recall@5']:>7.3f}{s['recall@10']:>7.3f}{s['mrr@10']:>7.3f}{s['ndcg@10']:>7.3f}"
              f"{s['no_hit@10']:>5}{s['decision_in_top10_eval']:>5}{s['relevant_decision_in_top10_eval']:>5}"
              f"{s['unlabeled_in_top10_eval']:>5}{s['control_top1_mean']:>8.3f}{s['eval_top1_mean']:>8.3f}")
    print("\n첫 정답 순위:", json.dumps(report["focus_first_relevant_rank"], ensure_ascii=False))
    print(f"평가 {len(eval_ids)}개, 대조군 {control_ids} | d 채움 {len(fills)}건 | label_delta2 {len(delta_rows)}행 | "
          f"토큰 {tokens:,} 비용 ${emb_cost:.6f}")


# ---------------------------------------------------------------- 2차: 종류별 후보 분리 (--mix2)
#
#   g) CASE·STANDARD 청크에서 후보 50, DECISION 청크(CLAUSE 제외)에서 후보 50 을 따로 뽑아 각각 자료 단위로 묶고
#      CASE·STANDARD 상위 7 + DECISION 상위 3 (모자라면 다른 쪽으로 채움) → 점수순. 11위부터는 남은 후보 점수순
#   h) CASE·STANDARD 후보 50 + DECISION_SUMMARY 후보 50 을 따로 뽑아 합친 뒤 점수순
#   (a·b·d·e·f 는 위와 같음. 점수는 모두 b 방식, e 만 상위 2개 청크 평균)
#   label_delta3: 상위 10 의 라벨 없는 자료 중 label_delta2 에도 없는 것 (label_delta2 는 라벨 대기 중)

DELTA3_FILE = GOLD_DIR / "label_delta3.csv"
REVIEW3_FILE = GOLD_DIR / "review_input_delta3.json"
REPORT2_FILE = RAW_DIR / "_report" / "retrieval_eval_mix2.json"
CONFIG_DESC = {
    "a": "CASE + STANDARD 만 (기준선)",
    "b": "+ DECISION, 자료 점수 = 청크 최고점",
    "d": f"자리 나누기 CASE·STANDARD {SPLIT_BASE} + DECISION {SPLIT_DECISION} (후보 50 공유)",
    "e": "점수 보정: 상위 2개 청크 점수 평균",
    "f": "DECISION 은 DECISION_SUMMARY 만 (후보 50 공유)",
    "g": f"종류별 후보 50 분리 + CASE·STANDARD {SPLIT_BASE} + DECISION {SPLIT_DECISION}",
    "h": "종류별 후보 50 분리: CASE·STANDARD + DECISION_SUMMARY, 점수순",
}


def by_score(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (-r["score"], r["_tie"]))


def build_rankings(chunks: list[dict], qid: str, fills: dict[str, list[str]]) -> tuple[dict, dict]:
    """chunks: 이 질문의 점수 매긴 청크 (DECISION_CLAUSE 는 이미 뺀 것).
    반환: ({설정: 자료 순위}, {설정: 그 설정이 검색 대상으로 쓴 청크}) — 두 번째는 best_chunk 고르기용."""
    cs = [c for c in chunks if c["doc_kind"] in BASE_KINDS]
    dec = [c for c in chunks if c["doc_kind"] == "DECISION"]
    dsum = [c for c in dec if c["chunk_type"] == "DECISION_SUMMARY"]
    r = {"a": rank_cases(cs, W_VEC, W_KW), "b": rank_cases(chunks, W_VEC, W_KW)}
    r["d"] = rank_split(r["b"], fills.setdefault("d", []), qid)
    r["e"] = rank_top2(chunks)
    r["f"] = rank_cases(cs + dsum, W_VEC, W_KW)
    r["g"] = rank_split(by_score(r["a"] + rank_cases(dec, W_VEC, W_KW)), fills.setdefault("g", []), qid)
    r["h"] = by_score(r["a"] + rank_cases(dsum, W_VEC, W_KW))
    pools = {"a": cs, "b": chunks, "d": chunks, "e": chunks, "f": cs + dsum, "g": chunks, "h": cs + dsum}
    return r, pools


def score_all(queries: list[dict]):
    """질문 임베딩(OpenAI 1회) + 청크 점수 (DB 읽기 전용). 반환: ({질문: 청크(CLAUSE 제외)}, 토큰, 키)."""
    import openai
    key = openai_key()
    if not key:
        raise SystemExit("OPENAI_API_KEY 가 .env 와 환경 변수에 없습니다")
    mask = masker(key)
    client = openai.OpenAI(api_key=key, max_retries=3, timeout=120)
    try:
        vecs, tokens = embed_texts(client, [q["query_text"] for q in queries])
    except openai.APIError as e:
        raise SystemExit(mask(f"API 실패: {type(e).__name__} {getattr(e, 'status_code', '')}")) from None
    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")  # DB 쓰기 금지
    chunks = {q["id"]: [c for c in score_chunks(conn, q["query_text"], v) if c["chunk_type"] != "DECISION_CLAUSE"]
              for q, v in zip(queries, vecs)}
    conn.close()
    return chunks, tokens, key


def read_csv_keys(path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {(r["query_id"], r["case_key"]) for r in csv.DictReader(f)}


def eval_mix2() -> None:
    names = ["a", "e", "f", "g", "h"]
    queries, gold = load_inputs(LABEL_V2)
    labeled = load_labeled_keys(LABEL_V2)
    pending = read_csv_keys(DELTA2_FILE)  # label_delta2 (아직 라벨 안 매김)
    eval_ids = [q["id"] for q in queries if gold.get(q["id"])]
    control_ids = [q["id"] for q in queries if not gold.get(q["id"])]

    chunks, tokens, key = score_all(queries)
    fills: dict[str, list[str]] = {}
    rankings: dict[str, dict[str, list[dict]]] = {n: {} for n in names}
    pool_sizes: dict[str, dict[str, int]] = {}
    for qid, cs in chunks.items():
        r, _ = build_rankings(cs, qid, fills)
        for n in names:
            rankings[n][qid] = r[n]
        pool_sizes[qid] = {"case_standard_candidates": len(r["a"]),
                           "decision_candidates_g": sum(1 for x in r["g"] if is_decision(x)),
                           "decision_summary_candidates_h": sum(1 for x in r["h"] if is_decision(x))}

    results = []
    for n in names:
        rk = rankings[n]
        res = evaluate(f"{n}) {CONFIG_DESC[n]}", CONFIG_DESC[n], rk, gold, control_ids)
        unl = {q: [x["case_key"] for x in rk[q][:TOP_K] if x["case_key"] not in labeled.get(q, set())] for q in rk}
        dec = {q: [x["case_key"] for x in rk[q][:TOP_K] if is_decision(x)] for q in rk}
        res["summary"].update({
            "decision_in_top10_eval": sum(len(dec[q]) for q in eval_ids),
            "relevant_decision_in_top10_eval": sum(1 for q in eval_ids for k in dec[q] if gold[q].get(k)),
            "unlabeled_in_top10_eval": sum(len(unl[q]) for q in eval_ids),
            "unlabeled_in_top10_eval_pending_delta2": sum(1 for q in eval_ids for k in unl[q] if (q, k) in pending),
            "unlabeled_in_top10_control": sum(len(unl[q]) for q in control_ids),
            "control_top1": {q: res["controls"][q]["top1_score"] for q in control_ids},
        })
        res["unlabeled_top10"] = {q: v for q, v in unl.items() if v}
        res["decision_top10"] = {q: v for q, v in dec.items() if v}
        for q in control_ids:
            res["controls"][q]["top10"] = [{"rank": i, "case_key": x["case_key"], "title": x["title"],
                                            "score": round(x["score"], 4)} for i, x in enumerate(rk[q][:TOP_K], 1)]
        results.append(res)
    first_rank = {q: {n: res["first_relevant_rank"][q] for n, res in zip(names, results)} for q in eval_ids}

    qmap = {q["id"]: q for q in queries}
    qorder = [q["id"] for q in queries]
    delta: dict[tuple[str, str], dict] = {}
    for n in names:
        for qid, ranked in rankings[n].items():
            for i, x in enumerate(ranked[:TOP_K], 1):
                k = x["case_key"]
                if k in labeled.get(qid, set()) or (qid, k) in pending:
                    continue
                delta.setdefault((qid, k), {"title": x["title"], "ranks": {}})["ranks"][n] = i
    delta_rows = []
    for (qid, k), d in sorted(delta.items(), key=lambda kv: (qorder.index(kv[0][0]), min(kv[1]["ranks"].values()),
                                                              kv[0][1])):
        best = lambda ns: min((d["ranks"][n] for n in ns if n in d["ranks"]), default="")  # noqa: E731
        delta_rows.append({"query_id": qid, "clause_ref": qmap[qid].get("clause_ref", ""), "case_key": k,
                           "title": d["title"], "rank_A": d["ranks"].get("a", ""), "rank_B": best(("e", "f")),
                           "rank_C": best(("g", "h")), "is_hint": 1 if k in (qmap[qid].get("hint_cases") or []) else 0,
                           "relevance": "", "_ranks": d["ranks"]})
    if delta_rows:
        with DELTA3_FILE.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LABEL_COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(delta_rows)

    keys = ("recall@5", "recall@10", "mrr@10", "ndcg@10", "no_hit@10", "decision_in_top10_eval",
            "relevant_decision_in_top10_eval", "unlabeled_in_top10_eval", "unlabeled_in_top10_eval_pending_delta2",
            "unlabeled_in_top10_control", "control_top1_mean", "eval_top1_mean")
    emb_cost = cost(tokens, DEFAULT_MODEL)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_file": str(LABEL_V2.relative_to(RAW_DIR.parent.parent)),
        "pending_labels": str(DELTA2_FILE.relative_to(RAW_DIR.parent.parent)),
        "category": CATEGORY, "top_k": TOP_K, "candidate_chunks": CANDIDATE_CHUNKS,
        "weights": {"vector": W_VEC, "keyword": W_KW}, "excluded_chunk_type": "DECISION_CLAUSE",
        "configs": {n: CONFIG_DESC[n] for n in names},
        "eval_queries": eval_ids, "control_queries": control_ids,
        "usage": {"embedding_tokens": tokens, "embedding_cost_usd": emb_cost},
        "notes": [
            "라벨 없는 자료(v2 정답표에 없는 자료)는 오답으로 계산. label_delta2 에 올라 있지만 아직 라벨이 없는 자료도 오답",
            "N3 는 평가 질문 (대조군 G10·G30·N1·N2)",
            "label_delta3: 상위 10 의 라벨 없는 자료 중 label_delta2 에 없는 것. rank_A=a, rank_B=e·f 중 좋은 순위, "
            "rank_C=g·h 중 좋은 순위 (설정별 순위는 label_delta3.items)",
        ],
        "summary_table": [{"config": r["name"], **{k: r["summary"][k] for k in keys}} for r in results],
        "focus_first_relevant_rank": {q: first_rank.get(q) for q in FOCUS},
        "first_relevant_rank": first_rank,
        "split_fills": fills,
        "candidate_pool_sizes": pool_sizes,
        "label_delta3": {"file": str(DELTA3_FILE.relative_to(RAW_DIR.parent.parent)) if delta_rows else None,
                         "rows": len(delta_rows),
                         "items": [{k: v for k, v in r.items() if k in ("query_id", "case_key", "title", "_ranks")}
                                   for r in delta_rows]},
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert key not in text
    REPORT2_FILE.write_text(text, encoding="utf-8")

    print(f"{'설정':<4}{'R@5':>7}{'R@10':>7}{'MRR':>7}{'nDCG':>7}{'무적중':>5}{'D수':>5}{'D정답':>5}{'무라벨':>5}"
          f"{'(d2)':>5}{'대조1위':>8}{'평가1위':>8}")
    for r in results:
        s = r["summary"]
        print(f"{r['name'][:2]:<4}{s['recall@5']:>7.3f}{s['recall@10']:>7.3f}{s['mrr@10']:>7.3f}{s['ndcg@10']:>7.3f}"
              f"{s['no_hit@10']:>5}{s['decision_in_top10_eval']:>5}{s['relevant_decision_in_top10_eval']:>5}"
              f"{s['unlabeled_in_top10_eval']:>5}{s['unlabeled_in_top10_eval_pending_delta2']:>5}"
              f"{s['control_top1_mean']:>8.3f}{s['eval_top1_mean']:>8.3f}")
    print("\n첫 정답 순위:", json.dumps(report["focus_first_relevant_rank"], ensure_ascii=False))
    print(f"평가 {len(eval_ids)}개, 대조군 {control_ids} | g 채움 {len(fills.get('g', []))}건 | "
          f"label_delta3 {len(delta_rows)}행 | 토큰 {tokens:,} 비용 ${emb_cost:.6f}")
    if delta_rows:
        from review_input_delta import build_review
        build_review(DELTA3_FILE, REVIEW3_FILE, ["g", "h", "e", "f", "a"])


# ---------------------------------------------------------------- 3차: 개념 태그 (--concept)
#
#   g)  확정 방식 (종류별 후보 50 분리, CASE·STANDARD 7 + DECISION 3), 개념 태그 없음
#   k1/k2/k3) 질의 개념(query_concepts.json)과 자료 개념(case_tag CONCEPT/LLM)이 하나라도 겹치는 자료를
#       그 종류의 후보에 강제로 넣고 자료 점수에 +0.05 / +0.10 / +0.20. 그 뒤 7+3 규칙은 g 와 같음
#   자료 점수는 g 와 같은 rank_cases 방식: 0.7 × (1 - 자료 최소 거리) + 0.3 × 자료 최대 word_similarity

from retrieval_eval import case_key  # noqa: E402

LABEL_V3 = GOLD_DIR / "label_sheet_final_v3.csv"
QUERY_CONCEPTS = GOLD_DIR / "query_concepts.json"
VOCAB_FILE = GOLD_DIR / "concept_vocab.json"
DELTA4_FILE = GOLD_DIR / "label_delta4.csv"
REVIEW4_FILE = GOLD_DIR / "review_input_delta4.json"
REPORT_CONCEPT = RAW_DIR / "_report" / "retrieval_eval_concept.json"
USAGE_FILE = RAW_DIR / "_report" / "concept_llm_usage.json"
CONTROLS = ["G10", "G30", "N1", "N2"]  # 사용자 확정 (N3 는 평가 질문)
BONUS = {"k1": 0.05, "k2": 0.10, "k3": 0.20}
CONCEPT_DESC = {"g": CONFIG_DESC["g"] + " (개념 태그 없음)",
                **{k: f"g + 개념 겹치는 자료 강제 포함 + 점수 +{b:.2f}" for k, b in BONUS.items()}}


def rank_forced(chunks: list[dict], forced: set[int], bonus: float) -> tuple[list[dict], int]:
    """rank_cases 와 같은 점수에 후보 강제 포함 + 가점. forced = 개념이 겹치는 dispute_case_id.
    반환: (순위, 후보 50 청크 밖에서 강제로 들어온 자료 수)."""
    by_dist = sorted(chunks, key=lambda c: (c["distance"], c["id"]))
    pool = list(dict.fromkeys(c["dispute_case_id"] for c in by_dist[:CANDIDATE_CHUNKS]))
    by_case: dict[int, list[dict]] = {}
    for c in chunks:
        by_case.setdefault(c["dispute_case_id"], []).append(c)
    extra = [cid for cid in by_case if cid in forced and cid not in set(pool)]
    ranked = []
    for cid in pool + extra:
        cs = by_case[cid]
        sim, kw = 1 - min(c["distance"] for c in cs), max(c["keyword"] for c in cs)
        rep = max(cs, key=lambda c: (W_VEC * (1 - c["distance"]) + W_KW * c["keyword"], -c["id"]))
        hit = cid in forced
        ranked.append({"case_key": case_key(cs[0]["doc_kind"], cs[0]["source_key"]), "title": cs[0]["title"],
                       "score": W_VEC * sim + W_KW * kw + (bonus if hit else 0.0), "vector_sim": sim, "keyword": kw,
                       "concept_hit": hit, "forced": cid in extra, "_cid": cid, "_tie": rep["id"]})
    return by_score(ranked), len(extra)


def concept_rankings(chunks: list[dict], qid: str, overlap: set[int], fills: dict) -> tuple[dict, dict, dict]:
    """반환: ({설정: 순위}, {설정: 청크(best_chunk 용)}, {설정: 강제 포함 수})."""
    cs = [c for c in chunks if c["doc_kind"] in BASE_KINDS]
    dec = [c for c in chunks if c["doc_kind"] == "DECISION"]
    base, _ = build_rankings(chunks, qid, {})
    r, forced_n = {"g": base["g"]}, {"g": 0}
    for name, bonus in BONUS.items():
        r_cs, n_cs = rank_forced(cs, overlap, bonus)
        r_dec, n_dec = rank_forced(dec, overlap, bonus)
        r[name] = rank_split(by_score(r_cs + r_dec), fills.setdefault(name, []), qid)
        forced_n[name] = n_cs + n_dec
    # 자기 점검: 가점 0·강제 없음이면 g 와 같아야 한다
    r0 = rank_split(by_score(rank_forced(cs, set(), 0.0)[0] + rank_forced(dec, set(), 0.0)[0]), [], qid)
    assert [x["case_key"] for x in r0] == [x["case_key"] for x in base["g"]], f"{qid}: k(0) != g"
    return r, {n: chunks for n in r}, forced_n


def load_concepts() -> tuple[dict[str, set[str]], dict[int, set[str]], dict[int, str]]:
    q = json.loads(QUERY_CONCEPTS.read_text(encoding="utf-8"))["queries"]
    query = {qid: {c["name"] for c in cs} for qid, cs in q.items()}
    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")
    docs: dict[int, set[str]] = {}
    for cid, value in conn.execute("SELECT dispute_case_id, value FROM case_tag WHERE axis = 'CONCEPT' AND source = 'LLM'"):
        docs.setdefault(cid, set()).add(value)
    keys = {cid: case_key(k, s) for cid, k, s in conn.execute(
        "SELECT id, doc_kind, source_key FROM dispute_case WHERE category = %s", (CATEGORY,))}
    conn.close()
    return query, docs, keys


def tag_stats() -> dict:
    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")
    rows = conn.execute("""
        SELECT d.doc_kind, count(t.id) FROM dispute_case d
        LEFT JOIN case_tag t ON t.dispute_case_id = d.id AND t.axis = 'CONCEPT' AND t.source = 'LLM'
        WHERE d.category = %s AND coalesce(d.meta->>'disposition', '') <> '각하'
        GROUP BY d.id, d.doc_kind""", (CATEGORY,)).fetchall()
    by_value = conn.execute("""SELECT value, count(*) FROM case_tag WHERE axis = 'CONCEPT' AND source = 'LLM'
                               GROUP BY 1 ORDER BY 2 DESC, 1""").fetchall()
    conf = [float(r[0]) for r in conn.execute(
        "SELECT confidence FROM case_tag WHERE axis = 'CONCEPT' AND source = 'LLM'")]
    conn.close()
    dist: dict[str, dict[int, int]] = {}
    for kind, n in rows:
        dist.setdefault(kind, {}).setdefault(n, 0)
        dist[kind][n] += 1
    total = {}
    for d in dist.values():
        for n, c in d.items():
            total[n] = total.get(n, 0) + c
    return {"documents": len(rows), "tags": sum(n for _, n in rows),
            "tags_per_document": dict(sorted(total.items())),
            "tags_per_document_by_kind": {k: dict(sorted(v.items())) for k, v in dist.items()},
            "documents_without_tags": total.get(0, 0),
            "confidence": {"min": min(conf), "median": sorted(conf)[len(conf) // 2], "max": max(conf)} if conf else None,
            "by_concept": [{"concept": v, "documents": n} for v, n in by_value]}


def eval_concept() -> None:
    names = ["g", "k1", "k2", "k3"]
    queries, gold = load_inputs(LABEL_V3)
    labeled = load_labeled_keys(LABEL_V3)
    eval_ids = [q["id"] for q in queries if q["id"] not in CONTROLS]
    no_gold = [q for q in eval_ids if not gold.get(q)]
    if no_gold:
        raise SystemExit(f"정답 없는 평가 질문: {no_gold}")
    control_ids = list(CONTROLS)
    qconcepts, dconcepts, keys = load_concepts()
    vocab = json.loads(VOCAB_FILE.read_text(encoding="utf-8"))

    chunks, tokens, key = score_all(queries)
    fills: dict[str, list[str]] = {}
    rankings: dict[str, dict[str, list[dict]]] = {n: {} for n in names}
    per_query_concept = {}
    for q in queries:
        qid = q["id"]
        overlap = {cid for cid, cs in dconcepts.items() if cs & qconcepts.get(qid, set())}
        r, _, forced_n = concept_rankings(chunks[qid], qid, overlap, fills)
        for n in names:
            rankings[n][qid] = r[n]
        per_query_concept[qid] = {
            "query_concepts": sorted(qconcepts.get(qid, set())),
            "overlap_documents": len(overlap),
            "overlap_relevant": sorted(keys[c] for c in overlap if c in keys and gold.get(qid, {}).get(keys[c])),
            "forced_into_pool": forced_n,
            "concept_hits_in_top10": {n: sum(1 for x in r[n][:TOP_K] if x.get("concept_hit")) for n in names},
        }

    results = []
    for n in names:
        rk = rankings[n]
        res = evaluate(f"{n}) {CONCEPT_DESC[n]}", CONCEPT_DESC[n], rk, gold, control_ids)
        unl = {q: [x["case_key"] for x in rk[q][:TOP_K] if x["case_key"] not in labeled.get(q, set())] for q in rk}
        dec = {q: [x["case_key"] for x in rk[q][:TOP_K] if is_decision(x)] for q in rk}
        res["summary"].update({
            "decision_in_top10_eval": sum(len(dec[q]) for q in eval_ids),
            "relevant_decision_in_top10_eval": sum(1 for q in eval_ids for k in dec[q] if gold[q].get(k)),
            "unlabeled_in_top10_eval": sum(len(unl[q]) for q in eval_ids),
            "unlabeled_in_top10_control": sum(len(unl[q]) for q in control_ids),
            "control_top1": {q: res["controls"][q]["top1_score"] for q in control_ids},
        })
        res["unlabeled_top10"] = {q: v for q, v in unl.items() if v}
        for q in control_ids:
            res["controls"][q]["top10"] = [{"rank": i, "case_key": x["case_key"], "title": x["title"],
                                            "score": round(x["score"], 4), "concept_hit": x.get("concept_hit", False)}
                                           for i, x in enumerate(rk[q][:TOP_K], 1)]
        results.append(res)
    first_rank = {q: {n: res["first_relevant_rank"][q] for n, res in zip(names, results)} for q in eval_ids}

    qmap = {q["id"]: q for q in queries}
    qorder = [q["id"] for q in queries]
    delta: dict[tuple[str, str], dict] = {}
    for n in names:
        for qid, ranked in rankings[n].items():
            for i, x in enumerate(ranked[:TOP_K], 1):
                if x["case_key"] not in labeled.get(qid, set()):
                    delta.setdefault((qid, x["case_key"]), {"title": x["title"], "ranks": {}})["ranks"][n] = i
    delta_rows = []
    for (qid, k), d in sorted(delta.items(), key=lambda kv: (qorder.index(kv[0][0]), min(kv[1]["ranks"].values()),
                                                              kv[0][1])):
        best = lambda ns: min((d["ranks"][n] for n in ns if n in d["ranks"]), default="")  # noqa: E731
        delta_rows.append({"query_id": qid, "clause_ref": qmap[qid].get("clause_ref", ""), "case_key": k,
                           "title": d["title"], "rank_A": d["ranks"].get("g", ""), "rank_B": best(("k1", "k2")),
                           "rank_C": d["ranks"].get("k3", ""),
                           "is_hint": 1 if k in (qmap[qid].get("hint_cases") or []) else 0, "relevance": "",
                           "_ranks": d["ranks"]})
    if delta_rows:
        with DELTA4_FILE.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LABEL_COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(delta_rows)

    usage = json.loads(USAGE_FILE.read_text(encoding="utf-8"))["runs"] if USAGE_FILE.exists() else []
    llm_total = {k: sum(r.get(k) or 0 for r in usage) for k in ("calls", "prompt_tokens", "completion_tokens", "cost_usd")}
    llm_total["cost_usd"] = round(llm_total["cost_usd"], 6)
    keys_sum = ("recall@5", "recall@10", "mrr@10", "ndcg@10", "no_hit@10", "decision_in_top10_eval",
                "relevant_decision_in_top10_eval", "unlabeled_in_top10_eval", "unlabeled_in_top10_control",
                "control_top1_mean", "eval_top1_mean")
    emb_cost = cost(tokens, DEFAULT_MODEL)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_file": str(LABEL_V3.relative_to(RAW_DIR.parent.parent)),
        "category": CATEGORY, "top_k": TOP_K, "candidate_chunks_per_kind": CANDIDATE_CHUNKS,
        "weights": {"vector": W_VEC, "keyword": W_KW}, "excluded_chunk_type": "DECISION_CLAUSE",
        "configs": CONCEPT_DESC, "bonus": BONUS,
        "eval_queries": eval_ids, "control_queries": control_ids,
        "concept_vocab": {"file": str(VOCAB_FILE.relative_to(RAW_DIR.parent.parent)), "count": vocab["count"],
                          "count_by_attempt": vocab.get("count_by_attempt"), "prompt_version": vocab.get("prompt_version"),
                          "supplement_added": (vocab.get("supplement") or {}).get("added"), "model": vocab["model"],
                          "names": [c["name"] for c in vocab["concepts"]]},
        "document_tags": tag_stats(),
        "query_concepts": {q: sorted(v) for q, v in qconcepts.items()},
        "queries_without_concepts": [q for q in qorder if not qconcepts.get(q)],
        "per_query_concept": per_query_concept,
        "llm_usage": {"runs": usage, "total": llm_total,
                      "note": "첫 개념 목록 시도 1회(83개, 범위 밖이라 저장 안 함)는 사용량 기록 전 코드라 토큰 미기록"},
        "embedding_usage": {"query_tokens": tokens, "cost_usd": emb_cost},
        "notes": [
            "라벨 없는 자료(v3 정답표에 없는 자료)는 오답으로 계산",
            "자료 점수는 g 확정 실험과 같은 rank_cases 방식: 0.7×(자료 안 최대 벡터 유사도) + 0.3×(자료 안 최대 키워드) "
            "— '청크 점수(0.7×벡터+0.3×키워드)의 최고점'과는 다를 수 있음 (같은 청크가 아닐 수 있음)",
            "k 의 가점은 개념이 하나라도 겹치면 한 번만 (겹친 개념 수와 무관)",
            "label_delta4: rank_A=g, rank_B=k1·k2 중 좋은 순위, rank_C=k3 (설정별 순위는 label_delta4.items)",
        ],
        "summary_table": [{"config": r["name"], **{k: r["summary"][k] for k in keys_sum}} for r in results],
        "focus_first_relevant_rank": {q: first_rank.get(q) for q in FOCUS},
        "first_relevant_rank": first_rank,
        "split_fills": fills,
        "label_delta4": {"file": str(DELTA4_FILE.relative_to(RAW_DIR.parent.parent)) if delta_rows else None,
                         "rows": len(delta_rows),
                         "items": [{k: v for k, v in r.items() if k in ("query_id", "case_key", "title", "_ranks")}
                                   for r in delta_rows]},
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert key not in text
    REPORT_CONCEPT.write_text(text, encoding="utf-8")

    print(f"{'설정':<5}{'R@5':>7}{'R@10':>7}{'MRR':>7}{'nDCG':>7}{'무적중':>5}{'D수':>5}{'D정답':>5}{'무라벨':>5}"
          f"{'대조1위':>8}{'평가1위':>8}")
    for r in results:
        s = r["summary"]
        print(f"{r['name'].split(')')[0]:<5}{s['recall@5']:>7.3f}{s['recall@10']:>7.3f}{s['mrr@10']:>7.3f}"
              f"{s['ndcg@10']:>7.3f}{s['no_hit@10']:>5}{s['decision_in_top10_eval']:>5}"
              f"{s['relevant_decision_in_top10_eval']:>5}{s['unlabeled_in_top10_eval']:>5}"
              f"{s['control_top1_mean']:>8.3f}{s['eval_top1_mean']:>8.3f}")
    print("\n첫 정답 순위:", json.dumps(report["focus_first_relevant_rank"], ensure_ascii=False))
    print(f"label_delta4 {len(delta_rows)}행 | LLM 누적 {llm_total} | 질의 임베딩 {tokens:,} 토큰")

    if delta_rows:
        from review_input_delta import build_review

        def ranker(qid: str, cs: list[dict]):
            overlap = {cid for cid, c in dconcepts.items() if c & qconcepts.get(qid, set())}
            r, pools, _ = concept_rankings(cs, qid, overlap, {})
            return r, pools
        build_review(DELTA4_FILE, REVIEW4_FILE, ["k1", "k2", "k3", "g"], ranker=ranker, label_name=LABEL_V3.name)
