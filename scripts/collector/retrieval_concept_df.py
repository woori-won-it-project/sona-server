"""흔한 개념(문서 빈도) 제외 비교 (retrieval_eval.py --concept-df 가 부른다). DB 는 읽기만 한다.

문서 빈도: case_tag CONCEPT(v3) 기준, 개념마다 태그가 붙은 자료 수 / 전체 자료 수
    (전체 = category='보험' 이고 각하 아닌 자료 438건) → data/raw/_gold/concept_df.json
설정 (모두 g 방식, 가점 +0.10, 겹치는 자료 강제 포함)
    g, k2 (이전 목록 80, v1 태그 스냅샷), k2v3 (새 목록 129, 제외 없음)
    k2v3_df05 / df10 / df20: 비율이 5% / 10% / 20% 를 넘는 개념은 자료·조항 양쪽에서 겹침 판단에서 뺌 (태그는 그대로).
        남은 조항 개념이 0개면 그 질문은 g 와 같은 결과
label_delta6.csv: label_delta5 전체 ∪ 위 설정들 상위 10 의 라벨 없는 자료 (중복 제거).
    rank_A=g, rank_B=k2, rank_C=k2v3 계열(k2v3·df05·df10·df20) 중 가장 좋은 순위 (설정별 순위는 보고서 label_delta6.items)
결과: data/raw/_report/retrieval_eval_concept_df.json, data/raw/_gold/review_input_delta6.json
"""
import csv
import json
from collections import Counter
from datetime import datetime, timezone

from collector import RAW_DIR, connect, load_env
from embedder import DEFAULT_MODEL, cost
from retrieval_concept_v3 import BONUS, DELTA5_FILE, EXTRA, VOCAB_V3, load_tag_sets
from retrieval_eval import BASE_KINDS, CANDIDATE_CHUNKS, CATEGORY, LABEL_COLUMNS, TOP_K, case_key, evaluate, \
    load_inputs, load_labeled_keys
from retrieval_mix import CONTROLS, FOCUS, GOLD_DIR, LABEL_V3, SPLIT_BASE, SPLIT_DECISION, W_KW, W_VEC, \
    build_rankings, by_score, is_decision, rank_forced, rank_split, score_all

DF_FILE = GOLD_DIR / "concept_df.json"
DELTA6_FILE = GOLD_DIR / "label_delta6.csv"
REVIEW6_FILE = GOLD_DIR / "review_input_delta6.json"
REPORT_FILE = RAW_DIR / "_report" / "retrieval_eval_concept_df.json"
THRESHOLDS = {"k2v3_df05": 0.05, "k2v3_df10": 0.10, "k2v3_df20": 0.20}
NAMES = ["g", "k2", "k2v3", *THRESHOLDS]
V3_FAMILY = ["k2v3", *THRESHOLDS]
DESC = {
    "g": "g: 종류별 후보 50 분리 + CASE·STANDARD 7 + DECISION 3 (개념 태그 없음)",
    "k2": "이전 목록 80, +0.10",
    "k2v3": "새 목록 129 + 글자 일치, 제외 없음, +0.10",
    **{n: f"새 목록 129 + 글자 일치, 문서 빈도 {t:.0%} 초과 개념 제외, +0.10" for n, t in THRESHOLDS.items()},
}


def document_frequency(doc_v3: dict[int, set[str]], write: bool = True) -> dict:
    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM dispute_case WHERE category = %s AND coalesce(meta->>'disposition', '') <> '각하'", (CATEGORY,))]
    conn.close()
    total = len(ids)
    counts = Counter(c for cid in ids for c in doc_v3.get(cid, set()))
    vocab = json.loads(VOCAB_V3.read_text(encoding="utf-8"))
    sources = {c["name"]: c["sources"] for c in vocab["concepts"]}
    rows = sorted(({"concept": n, "documents": counts.get(n, 0), "ratio": round(counts.get(n, 0) / total, 4),
                    "sources": sources.get(n, [])} for n in sources), key=lambda r: (-r["documents"], r["concept"]))
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "tags": "case_tag CONCEPT (v3: GPT ∪ 글자 일치)",
           "total_documents": total, "concepts": len(rows),
           "concepts_with_no_documents": sum(1 for r in rows if not r["documents"]), "df": rows}
    if write:
        DF_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def excluded_concepts(df: dict) -> dict[str, list[str]]:
    """설정별로 문서 빈도 비율이 기준을 넘는 개념 (비율 큰 순)."""
    ratio = {r["concept"]: r["ratio"] for r in df["df"]}
    return {n: sorted((c for c, r in ratio.items() if r > t), key=lambda c: -ratio[c]) for n, t in THRESHOLDS.items()}


def rank_concept(chunks: list[dict], qid: str, tag_set: dict, drop: set[str], bonus: float,
                 n_base: int = SPLIT_BASE, n_dec: int = SPLIT_DECISION) -> tuple[list[dict], int]:
    """g 방식 + 개념 겹치는 자료 강제 포함·가점 (drop 개념은 겹침 판단에서 뺌). 반환: (순위, 강제 포함 수).
    n_base·n_dec 로 상위 개수(CASE·STANDARD + DECISION)를 바꾼다 (기본 7 + 3)."""
    cs = [c for c in chunks if c["doc_kind"] in BASE_KINDS]
    dec = [c for c in chunks if c["doc_kind"] == "DECISION"]
    qc = tag_set["query"].get(qid, set()) - drop
    ov = {cid for cid, cc in tag_set["doc"].items() if (cc - drop) & qc}
    r_cs, f_cs = rank_forced(cs, ov, bonus)
    r_dec, f_dec = rank_forced(dec, ov, bonus)
    return rank_split(by_score(r_cs + r_dec), [], qid, n_base, n_dec), f_cs + f_dec


def eval_concept_df() -> None:
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
    df = document_frequency(tags["v3"]["doc"])
    ratio = {r["concept"]: r["ratio"] for r in df["df"]}
    excluded = excluded_concepts(df)

    def rank(qid: str, chunks: list[dict]):
        base, _ = build_rankings(chunks, qid, {})
        r, forced = {"g": base["g"]}, {"g": 0}
        specs = [("k2", "v1", set(), BONUS), ("k2v3", "v3", set(), BONUS),
                 *((n, "v3", set(excluded[n]), BONUS) for n in THRESHOLDS),
                 ("k1", "v1", set(), EXTRA["k1"]), ("k3", "v1", set(), EXTRA["k3"])]
        for name, tv, drop, bonus in specs:
            r[name], forced[name] = rank_concept(chunks, qid, tags[tv], drop, bonus)
            if not (tags[tv]["query"].get(qid, set()) - drop):  # 남은 조항 개념 0개 → g 와 같아야 함
                assert [x["case_key"] for x in r[name]] == [x["case_key"] for x in base["g"]], f"{qid} {name}"
        rank.forced = forced  # 마지막 질문의 강제 포함 수 (아래 루프에서 바로 읽음)
        return r, {n: chunks for n in r}

    chunks, tokens, key = score_all(queries)
    rankings = {n: {} for n in NAMES}
    forced_count = {n: {} for n in NAMES}
    remaining = {n: {} for n in V3_FAMILY}
    for q in queries:
        qid = q["id"]
        r, _ = rank(qid, chunks[qid])
        for n in NAMES:
            rankings[n][qid] = r[n]
            forced_count[n][qid] = rank.forced[n]
        for n in V3_FAMILY:
            drop = set(excluded.get(n, []))
            remaining[n][qid] = sorted(tags["v3"]["query"].get(qid, set()) - drop)

    results = []
    for n in NAMES:
        rk = rankings[n]
        res = evaluate(f"{n}) {DESC[n]}", DESC[n], rk, gold, control_ids)
        unl = {q: [x["case_key"] for x in rk[q][:TOP_K] if x["case_key"] not in labeled.get(q, set())] for q in rk}
        dec = {q: [x["case_key"] for x in rk[q][:TOP_K] if is_decision(x)] for q in rk}
        fc = forced_count[n]
        res["summary"].update({
            "forced_per_query_mean_all": round(sum(fc.values()) / len(fc), 2),
            "forced_per_query_mean_eval": round(sum(fc[q] for q in eval_ids) / len(eval_ids), 2),
            "bonus_in_top10_mean_all": round(sum(sum(1 for x in rk[q][:TOP_K] if x.get("concept_hit"))
                                                 for q in rk) / len(rk), 2),
            "decision_in_top10_eval": sum(len(dec[q]) for q in eval_ids),
            "relevant_decision_in_top10_eval": sum(1 for q in eval_ids for k in dec[q] if gold[q].get(k)),
            "unlabeled_in_top10_eval": sum(len(unl[q]) for q in eval_ids),
            "unlabeled_in_top10_control": sum(len(unl[q]) for q in control_ids),
            "control_top1": {q: res["controls"][q]["top1_score"] for q in control_ids},
        })
        res["forced_per_query"] = fc
        res["unlabeled_top10"] = {q: v for q, v in unl.items() if v}
        for q in control_ids:
            res["controls"][q]["top10"] = [{"rank": i, "case_key": x["case_key"], "title": x["title"],
                                            "score": round(x["score"], 4), "concept_hit": x.get("concept_hit", False)}
                                           for i, x in enumerate(rk[q][:TOP_K], 1)]
        results.append(res)
    first_rank = {q: {n: res["first_relevant_rank"][q] for n, res in zip(NAMES, results)} for q in eval_ids}

    # label_delta6 = label_delta5 전체 ∪ 모든 설정 상위 10 의 라벨 없는 자료
    qmap = {q["id"]: q for q in queries}
    qorder = [q["id"] for q in queries]
    titles, in5 = {}, set()
    with DELTA5_FILE.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            titles[(row["query_id"], row["case_key"])] = row["title"]
            in5.add((row["query_id"], row["case_key"]))
    wanted = set(in5)
    for n in NAMES:
        for qid, ranked in rankings[n].items():
            for x in ranked[:TOP_K]:
                if x["case_key"] not in labeled.get(qid, set()):
                    wanted.add((qid, x["case_key"]))
                    titles.setdefault((qid, x["case_key"]), x["title"])
    rows = []
    for qid, k in wanted:
        ranks = {n: next((i for i, x in enumerate(rankings[n][qid][:TOP_K], 1) if x["case_key"] == k), None)
                 for n in NAMES}
        fam = [ranks[n] for n in V3_FAMILY if ranks[n]]
        rows.append({"query_id": qid, "clause_ref": qmap[qid].get("clause_ref", ""), "case_key": k,
                     "title": titles[(qid, k)], "rank_A": ranks["g"] or "", "rank_B": ranks["k2"] or "",
                     "rank_C": min(fam) if fam else "", "is_hint": 1 if k in (qmap[qid].get("hint_cases") or []) else 0,
                     "relevance": "", "_ranks": {n: v for n, v in ranks.items() if v}, "_in_delta5": (qid, k) in in5})
    rows.sort(key=lambda r: (qorder.index(r["query_id"]), min(r["_ranks"].values(), default=99), r["case_key"]))
    with DELTA6_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    keys_sum = ("recall@5", "recall@10", "mrr@10", "ndcg@10", "no_hit@10", "forced_per_query_mean_all",
                "forced_per_query_mean_eval", "bonus_in_top10_mean_all", "relevant_decision_in_top10_eval",
                "unlabeled_in_top10_eval", "unlabeled_in_top10_control", "control_top1_mean", "eval_top1_mean")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_file": str(LABEL_V3.relative_to(RAW_DIR.parent.parent)),
        "category": CATEGORY, "top_k": TOP_K, "candidate_chunks_per_kind": CANDIDATE_CHUNKS,
        "weights": {"vector": W_VEC, "keyword": W_KW}, "bonus": BONUS, "configs": DESC,
        "eval_queries": eval_ids, "control_queries": control_ids,
        "document_frequency": {"file": str(DF_FILE.relative_to(RAW_DIR.parent.parent)),
                               "total_documents": df["total_documents"], "top20": df["df"][:20]},
        "excluded_concepts": {n: [{"concept": c, "ratio": ratio[c]} for c in excluded[n]] for n in THRESHOLDS},
        "excluded_count": {n: len(v) for n, v in excluded.items()},
        "remaining_query_concepts": remaining,
        "queries_with_no_remaining_concepts": {n: [q for q, v in remaining[n].items() if not v] for n in V3_FAMILY},
        "embedding_usage": {"query_tokens": tokens, "cost_usd": cost(tokens, DEFAULT_MODEL)},
        "llm_usage": {"calls": 0, "note": "이번 실행은 GPT 를 부르지 않음 (v3 태그·조항 개념 그대로)"},
        "notes": [
            "k2·k2v3 는 지난 실험과 같은 입력으로 다시 계산 (질의 임베딩만 새로 받음)",
            "제외는 겹침 판단(가점·강제 포함)에서만. case_tag 는 그대로",
            "라벨 없는 자료(v3 정답표에 없는 자료)는 오답. label_delta4·5 의 행은 아직 라벨 없음",
            "forced_per_query = 그 종류의 후보 50 청크 밖에서 개념 겹침으로 강제로 들어온 자료 수",
        ],
        "summary_table": [{"config": r["name"], **{k: r["summary"][k] for k in keys_sum}} for r in results],
        "focus_first_relevant_rank": {q: first_rank.get(q) for q in FOCUS},
        "first_relevant_rank": first_rank,
        "label_delta6": {"file": str(DELTA6_FILE.relative_to(RAW_DIR.parent.parent)), "rows": len(rows),
                         "from_label_delta5": sum(1 for r in rows if r["_in_delta5"]),
                         "new": sum(1 for r in rows if not r["_in_delta5"]),
                         "by_prefix": dict(Counter(r["case_key"][0] for r in rows)),
                         "items": [{k: r[k] for k in ("query_id", "case_key", "title", "_ranks")} for r in rows]},
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    assert key not in text
    REPORT_FILE.write_text(text, encoding="utf-8")

    print(f"{'설정':<11}{'R@5':>7}{'R@10':>7}{'MRR':>7}{'nDCG':>7}{'무적중':>5}{'강제':>6}{'무라벨':>5}{'대조1위':>8}")
    for r in results:
        s = r["summary"]
        print(f"{r['name'].split(')')[0]:<11}{s['recall@5']:>7.3f}{s['recall@10']:>7.3f}{s['mrr@10']:>7.3f}"
              f"{s['ndcg@10']:>7.3f}{s['no_hit@10']:>5}{s['forced_per_query_mean_all']:>6.1f}"
              f"{s['unlabeled_in_top10_eval']:>5}{s['control_top1_mean']:>8.3f}")
    print("\n첫 정답 순위:", json.dumps(report["focus_first_relevant_rank"], ensure_ascii=False))
    print("제외 개념 수:", report["excluded_count"])
    print(f"label_delta6 {len(rows)}행 (delta5 {report['label_delta6']['from_label_delta5']} + 새 {report['label_delta6']['new']})")

    from review_input_delta import build_review
    build_review(DELTA6_FILE, REVIEW6_FILE, ["k2v3_df10", "k2v3_df05", "k2v3_df20", "k2v3", "k2", "k1", "k3", "g"],
                 ranker=rank, label_name=LABEL_V3.name)
