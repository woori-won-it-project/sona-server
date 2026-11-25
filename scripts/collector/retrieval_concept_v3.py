"""개념 태그 v3 비교 (retrieval_eval.py --concept-v3 가 부른다). DB 는 읽기만 한다.

정답: data/raw/_gold/label_sheet_final_v3.csv, 대조군 G10·G30·N1·N2 (N3 은 평가 질문)
설정 (모두 g 방식: 종류별 후보 50 분리, CASE·STANDARD 7 + DECISION 3, C 0.7/0.3, DECISION_CLAUSE 제외)
    g     개념 태그 없음
    k2    이전 개념 목록(80개): 자료 태그 = concept_tags_v1_snapshot.json (v3 로 바꾸기 전 case_tag 를 떠 둔 것),
          조항 개념 = query_concepts.json. 겹치는 자료 강제 포함 + 0.10
    k2v3  새 개념 목록(129개): 자료 태그 = case_tag CONCEPT (GPT ∪ 글자 일치), 조항 개념 = query_concepts_v3.json (GPT ∪ 글자 일치).
          겹치는 자료 강제 포함 + 0.10
    (label_delta4 행의 best_chunk 용으로 k1·k3(이전 목록 +0.05/+0.20)도 순위만 계산)
대조군 넓은 개념: 대조군 질문마다 가점을 받은 자료(후보에 든 자료)에서 겹친 개념을 세어 상위 10 (상위 10 안 자료 기준도 같이)
label_delta5.csv: label_delta4 전체 ∪ k2·k2v3 상위 10 의 라벨 없는 자료 (중복 제거). rank_A=g, rank_B=k2, rank_C=k2v3 (이번 실행 순위)
결과: data/raw/_report/retrieval_eval_concept_v3.json, review_input_delta5.json
"""
import csv
import json
from collections import Counter
from datetime import datetime, timezone

from collector import RAW_DIR, connect, load_env
from embedder import DEFAULT_MODEL, cost
from retrieval_eval import BASE_KINDS, CANDIDATE_CHUNKS, CATEGORY, LABEL_COLUMNS, TOP_K, case_key, evaluate, \
    load_inputs, load_labeled_keys
from retrieval_mix import CONTROLS, DELTA4_FILE, FOCUS, GOLD_DIR, LABEL_V3, USAGE_FILE, W_KW, W_VEC, build_rankings, \
    by_score, is_decision, rank_forced, rank_split, read_csv_keys, score_all

SNAPSHOT_V1 = GOLD_DIR / "concept_tags_v1_snapshot.json"
QUERY_V1 = GOLD_DIR / "query_concepts.json"
QUERY_V3 = GOLD_DIR / "query_concepts_v3.json"
VOCAB_V1 = GOLD_DIR / "concept_vocab.json"
VOCAB_V3 = GOLD_DIR / "concept_vocab_v3.json"
TAGS_V3 = GOLD_DIR / "concept_tags_v3.json"
DELTA5_FILE = GOLD_DIR / "label_delta5.csv"
REVIEW5_FILE = GOLD_DIR / "review_input_delta5.json"
REPORT_FILE = RAW_DIR / "_report" / "retrieval_eval_concept_v3.json"
BONUS = 0.10
DESC = {
    "g": "g: 종류별 후보 50 분리 + CASE·STANDARD 7 + DECISION 3 (개념 태그 없음)",
    "k2": "g + 이전 개념 목록(80) 겹치는 자료 강제 포함 + 0.10",
    "k2v3": "g + 새 개념 목록(129, 약관 용어 정의 보완) + 글자 일치 보조, 강제 포함 + 0.10",
}
EXTRA = {"k1": 0.05, "k3": 0.20}  # label_delta4 의 출처 설정 (이전 목록)


def load_tag_sets(keys_to_id: dict[str, int]) -> dict[str, dict]:
    v1 = json.loads(SNAPSHOT_V1.read_text(encoding="utf-8"))["tags"]
    doc_v1 = {keys_to_id[k]: {t["name"] for t in ts} for k, ts in v1.items() if k in keys_to_id}
    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")
    doc_v3: dict[int, set[str]] = {}
    for cid, value in conn.execute("SELECT dispute_case_id, value FROM case_tag WHERE axis = 'CONCEPT'"):
        doc_v3.setdefault(cid, set()).add(value)
    conn.close()
    q1 = {q: {c["name"] for c in cs} for q, cs in json.loads(QUERY_V1.read_text(encoding="utf-8"))["queries"].items()}
    q3 = {q: {c["name"] for c in cs} for q, cs in json.loads(QUERY_V3.read_text(encoding="utf-8"))["queries"].items()}
    return {"v1": {"doc": doc_v1, "query": q1}, "v3": {"doc": doc_v3, "query": q3}}


def overlap_ids(tags: dict, qid: str) -> set[int]:
    qc = tags["query"].get(qid, set())
    return {cid for cid, cs in tags["doc"].items() if cs & qc}


def ranker_for(tags: dict):
    def rank(qid: str, chunks: list[dict]):
        cs = [c for c in chunks if c["doc_kind"] in BASE_KINDS]
        dec = [c for c in chunks if c["doc_kind"] == "DECISION"]
        base, _ = build_rankings(chunks, qid, {})
        r = {"g": base["g"]}
        ov1, ov3 = overlap_ids(tags["v1"], qid), overlap_ids(tags["v3"], qid)
        for name, ov, bonus in (("k2", ov1, BONUS), ("k2v3", ov3, BONUS),
                                ("k1", ov1, EXTRA["k1"]), ("k3", ov1, EXTRA["k3"])):
            r_cs, _ = rank_forced(cs, ov, bonus)
            r_dec, _ = rank_forced(dec, ov, bonus)
            r[name] = rank_split(by_score(r_cs + r_dec), [], qid)
        return r, {n: chunks for n in r}
    return rank


def eval_concept_v3() -> None:
    names = ["g", "k2", "k2v3"]
    queries, gold = load_inputs(LABEL_V3)
    labeled = load_labeled_keys(LABEL_V3)
    eval_ids = [q["id"] for q in queries if q["id"] not in CONTROLS]
    if [q for q in eval_ids if not gold.get(q)]:
        raise SystemExit("정답 없는 평가 질문이 있습니다")
    control_ids = list(CONTROLS)

    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")
    keys = {cid: case_key(k, s) for cid, k, s in conn.execute(
        "SELECT id, doc_kind, source_key FROM dispute_case WHERE category = %s", (CATEGORY,))}
    conn.close()
    tags = load_tag_sets({v: k for k, v in keys.items()})
    rank = ranker_for(tags)

    chunks, tokens, key = score_all(queries)
    rankings: dict[str, dict[str, list[dict]]] = {n: {} for n in names}
    per_query, control_concepts, control_concepts_top10 = {}, {"k2": Counter(), "k2v3": Counter()}, \
        {"k2": Counter(), "k2v3": Counter()}
    all_concepts_top10 = {"k2": Counter(), "k2v3": Counter()}
    for q in queries:
        qid = q["id"]
        r, _ = rank(qid, chunks[qid])
        for n in names:
            rankings[n][qid] = r[n]
        info = {"query_concepts_v1": sorted(tags["v1"]["query"].get(qid, set())),
                "query_concepts_v3": sorted(tags["v3"]["query"].get(qid, set()))}
        for n, tv in (("k2", "v1"), ("k2v3", "v3")):
            qc = tags[tv]["query"].get(qid, set())
            hits = [x for x in r[n] if x.get("concept_hit")]
            info[f"{n}_bonus_candidates"] = len(hits)
            info[f"{n}_bonus_in_top10"] = sum(1 for x in r[n][:TOP_K] if x.get("concept_hit"))
            info[f"{n}_forced_into_pool"] = sum(1 for x in r[n] if x.get("forced"))
            for i, x in enumerate(hits):
                shared = tags[tv]["doc"].get(x["_cid"], set()) & qc
                in_top = any(y is x for y in r[n][:TOP_K])
                if qid in control_ids:
                    control_concepts[n].update(shared)
                    if in_top:
                        control_concepts_top10[n].update(shared)
                if in_top:
                    all_concepts_top10[n].update(shared)
        per_query[qid] = info

    results = []
    for n in names:
        rk = rankings[n]
        res = evaluate(f"{n}) {DESC[n]}", DESC[n], rk, gold, control_ids)
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
        for pq in res["per_query"].values():  # _cid 등 내부 키는 넣지 않음 (evaluate 가 top10 을 새로 만든다)
            pass
        results.append(res)
    first_rank = {q: {n: res["first_relevant_rank"][q] for n, res in zip(names, results)} for q in eval_ids}

    # label_delta5 = label_delta4 ∪ (k2 ∪ k2v3 상위 10 의 라벨 없는 자료)
    qmap = {q["id"]: q for q in queries}
    qorder = [q["id"] for q in queries]
    pending4 = read_csv_keys(DELTA4_FILE)
    titles = {}
    with DELTA4_FILE.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            titles[(row["query_id"], row["case_key"])] = row["title"]
    wanted = {k: "label_delta4" for k in pending4}
    for n in ("k2", "k2v3"):
        for qid, ranked in rankings[n].items():
            for x in ranked[:TOP_K]:
                if x["case_key"] not in labeled.get(qid, set()):
                    wanted.setdefault((qid, x["case_key"]), f"top10 {n}")
                    titles.setdefault((qid, x["case_key"]), x["title"])
    rows = []
    for (qid, k), origin in wanted.items():
        ranks = {n: next((i for i, x in enumerate(rankings[n][qid][:TOP_K], 1) if x["case_key"] == k), "")
                 for n in names}
        rows.append({"query_id": qid, "clause_ref": qmap[qid].get("clause_ref", ""), "case_key": k,
                     "title": titles[(qid, k)], "rank_A": ranks["g"], "rank_B": ranks["k2"], "rank_C": ranks["k2v3"],
                     "is_hint": 1 if k in (qmap[qid].get("hint_cases") or []) else 0, "relevance": "",
                     "_origin": origin, "_in_delta4": (qid, k) in pending4})
    rows.sort(key=lambda r: (qorder.index(r["query_id"]), min([v for v in (r["rank_A"], r["rank_B"], r["rank_C"])
                                                                 if v != ""] or [99]), r["case_key"]))
    with DELTA5_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    v1 = json.loads(VOCAB_V1.read_text(encoding="utf-8"))
    v3 = json.loads(VOCAB_V3.read_text(encoding="utf-8"))
    tv3 = json.loads(TAGS_V3.read_text(encoding="utf-8"))["tags"]
    per_doc = Counter(len(ts) for ts in tv3.values())
    methods = Counter(m for ts in tv3.values() for t in ts for m in t["methods"])
    only_literal = sum(1 for ts in tv3.values() for t in ts if t["methods"] == ["literal"])
    by_concept = Counter(t["name"] for ts in tv3.values() for t in ts)
    usage = json.loads(USAGE_FILE.read_text(encoding="utf-8"))["runs"] if USAGE_FILE.exists() else []
    v3_runs = [u for u in usage if u["stage"] in ("policy", "tag3", "query3", "all3")]
    total = lambda runs: {k: round(sum(r.get(k) or 0 for r in runs), 6)  # noqa: E731
                          for k in ("calls", "prompt_tokens", "completion_tokens", "cost_usd")}
    qz = json.loads(QUERY_V3.read_text(encoding="utf-8"))["zero_concept_queries"]
    keys_sum = ("recall@5", "recall@10", "mrr@10", "ndcg@10", "no_hit@10", "decision_in_top10_eval",
                "relevant_decision_in_top10_eval", "unlabeled_in_top10_eval", "unlabeled_in_top10_control",
                "control_top1_mean", "eval_top1_mean")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_file": str(LABEL_V3.relative_to(RAW_DIR.parent.parent)),
        "category": CATEGORY, "top_k": TOP_K, "candidate_chunks_per_kind": CANDIDATE_CHUNKS,
        "weights": {"vector": W_VEC, "keyword": W_KW}, "bonus": BONUS, "configs": DESC,
        "eval_queries": eval_ids, "control_queries": control_ids,
        "vocab": {"v1": {"count": v1["count"]},
                  "v3": {"count": v3["count"], "count_by_source": v3["count_by_source"],
                         "merged_into_existing": v3["policy"]["merged_into_existing"],
                         "added": v3["policy"]["added"], "merge_rejected": v3["policy"]["merge_rejected"],
                         "dropped_long_names": v3["policy"]["dropped_long_names"],
                         "folded_new_terms": v3["policy"]["folded_new_terms"]}},
        "document_tags_v3": {"documents": len(tv3), "tags": sum(len(t) for t in tv3.values()),
                             "tags_per_document": dict(sorted(per_doc.items())),
                             "documents_without_tags": per_doc.get(0, 0),
                             "by_method": dict(methods), "literal_only_tags": only_literal,
                             "top_concepts": by_concept.most_common(20)},
        "query_concepts": {"zero_concept_queries": {"v1": qz["v1"], "v3": qz["v3"],
                                                    "count_v1": len(qz["v1"]), "count_v3": len(qz["v3"])},
                           "v3": {q: sorted(v) for q, v in tags["v3"]["query"].items()}},
        "control_overlap_concepts_top10": {
            n: {"bonus_candidates": control_concepts[n].most_common(10),
                "bonus_in_top10": control_concepts_top10[n].most_common(10)} for n in ("k2", "k2v3")},
        "all_queries_overlap_concepts_in_top10": {n: all_concepts_top10[n].most_common(15) for n in ("k2", "k2v3")},
        "per_query": per_query,
        "llm_usage": {"v3_runs": v3_runs, "v3_total": total(v3_runs), "all_runs_total": total(usage)},
        "embedding_usage": {"query_tokens": tokens, "cost_usd": cost(tokens, DEFAULT_MODEL)},
        "notes": [
            "k2 는 이전 실험과 같은 입력(v1 태그 스냅샷·v1 조항 개념)으로 다시 계산 (질의 임베딩은 새로 받음)",
            "라벨 없는 자료(v3 정답표에 없는 자료)는 오답. label_delta4 의 56행은 아직 라벨이 없으므로 오답",
            "가점은 개념이 하나라도 겹치면 한 번만 (겹친 개념 수와 무관)",
            "자료 개념은 case_tag CONCEPT 전부 (GPT 선택 = source 'LLM', 글자 일치로만 붙은 것 = 'RULE'). "
            "방법별 상세는 concept_tags_v3.json 의 methods",
        ],
        "summary_table": [{"config": r["name"], **{k: r["summary"][k] for k in keys_sum}} for r in results],
        "focus_first_relevant_rank": {q: first_rank.get(q) for q in FOCUS},
        "first_relevant_rank": first_rank,
        "label_delta5": {"file": str(DELTA5_FILE.relative_to(RAW_DIR.parent.parent)), "rows": len(rows),
                         "from_label_delta4": sum(1 for r in rows if r["_in_delta4"]),
                         "new": sum(1 for r in rows if not r["_in_delta4"]),
                         "by_prefix": dict(Counter(r["case_key"][0] for r in rows))},
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    assert key not in text
    REPORT_FILE.write_text(text, encoding="utf-8")

    print(f"{'설정':<6}{'R@5':>7}{'R@10':>7}{'MRR':>7}{'nDCG':>7}{'무적중':>5}{'D정답':>5}{'무라벨':>5}{'대조1위':>8}")
    for r in results:
        s = r["summary"]
        print(f"{r['name'].split(')')[0]:<6}{s['recall@5']:>7.3f}{s['recall@10']:>7.3f}{s['mrr@10']:>7.3f}"
              f"{s['ndcg@10']:>7.3f}{s['no_hit@10']:>5}{s['relevant_decision_in_top10_eval']:>5}"
              f"{s['unlabeled_in_top10_eval']:>5}{s['control_top1_mean']:>8.3f}")
    print("\n첫 정답 순위:", json.dumps(report["focus_first_relevant_rank"], ensure_ascii=False))
    print("대조군 겹친 개념:", json.dumps(report["control_overlap_concepts_top10"], ensure_ascii=False))
    print(f"개념 0개 질문 v1 {len(qz['v1'])} → v3 {len(qz['v3'])} | label_delta5 {len(rows)}행")

    from review_input_delta import build_review
    build_review(DELTA5_FILE, REVIEW5_FILE, ["k2v3", "k2", "k1", "k3", "g"], ranker=rank, label_name=LABEL_V3.name)
