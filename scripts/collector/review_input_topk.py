"""K=20 에서 11~20위로 새로 들어온 라벨 없는 자료의 채점 입력 만들기 (이슈 #12). DB 는 읽기만, API 호출 없음.

입력: data/raw/_report/retrieval_eval_topk.json (retrieval_topk.py 결과, K=20 의 unlabeled_beyond10)
      data/raw/_gold/label_sheet_final_v4.csv (정답표에 없는지 다시 확인), gold_queries.json (질문 본문)
출력: data/raw/_gold/review_input_topk.json
    질문별 {query_id, clause_ref, query_text, is_control, candidates: [
        {case_key, doc_kind, title, rank_at_k20, 본문}]}
    본문  CASE:      complaint(민원내용), dispute_issue(쟁점), decision_reason(처리결과)
          STANDARD:  summary(요지). 비어 있으면 STANDARD_SUMMARY 청크 내용을 summary_chunk 로
          DECISION:  summary_chunk (DECISION_SUMMARY), judgment_chunks (DECISION_JUDGMENT 전부, chunk_index 순)

사용 (scripts/collector 에서): python review_input_topk.py
"""
import json
from datetime import datetime, timezone

from collector import RAW_DIR, connect, load_env
from retrieval_eval import QUERIES_FILE, case_key, load_labeled_keys
from retrieval_mix import CONTROLS, GOLD_DIR

LABEL_V4 = GOLD_DIR / "label_sheet_final_v4.csv"
TOPK_REPORT = RAW_DIR / "_report" / "retrieval_eval_topk.json"
OUT_FILE = GOLD_DIR / "review_input_topk.json"
K = "20"


def load_documents(conn, keys: set[str]) -> dict[str, dict]:
    docs, ids = {}, {}
    for cid, doc_kind, source_key, title, summary, complaint, dispute_issue, decision_reason in conn.execute(
            """SELECT id, doc_kind, source_key, title, summary, complaint, dispute_issue, decision_reason
               FROM dispute_case"""):
        k = case_key(doc_kind, source_key)
        if k not in keys:
            continue
        ids[cid] = k
        d = {"doc_kind": doc_kind, "title": title}
        if doc_kind == "CASE":
            d.update(complaint=complaint, dispute_issue=dispute_issue, decision_reason=decision_reason)
        elif doc_kind == "STANDARD":
            d.update(summary=summary)
        else:
            d.update(summary_chunk=None, judgment_chunks=[])
        docs[k] = d
    for cid, chunk_type, idx, heading, content in conn.execute(
            """SELECT dispute_case_id, chunk_type, chunk_index, heading, content FROM case_chunk
               WHERE dispute_case_id = ANY(%s)
                 AND chunk_type IN ('DECISION_SUMMARY', 'DECISION_JUDGMENT', 'STANDARD_SUMMARY')
               ORDER BY dispute_case_id, chunk_type, chunk_index""", (list(ids),)):
        d = docs[ids[cid]]
        if chunk_type == "DECISION_JUDGMENT":
            d["judgment_chunks"].append({"chunk_index": idx, "heading": heading, "content": content})
        elif chunk_type == "DECISION_SUMMARY":
            d["summary_chunk"] = content
        elif not d.get("summary"):
            d["summary_chunk"] = content
    return docs


def main() -> None:
    report = json.loads(TOPK_REPORT.read_text(encoding="utf-8"))
    rows = report["per_k"][K]["per_query"]
    queries = {q["id"]: q for q in json.loads(QUERIES_FILE.read_text(encoding="utf-8"))["queries"]}
    labeled = load_labeled_keys(LABEL_V4)
    qids = [*report["eval_queries"], *report["control_queries"]]

    pairs = {q: rows[q]["unlabeled_beyond10"] for q in qids if rows[q]["unlabeled_beyond10"]}
    again = [(q, c) for q, cs in pairs.items() for c in cs if c in labeled.get(q, set())]
    if again:
        raise SystemExit(f"정답표에 이미 있는 쌍: {again}")

    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")  # DB 쓰기 금지
    wanted = {c for cs in pairs.values() for c in cs}
    docs = load_documents(conn, wanted)
    conn.close()
    missing = sorted(wanted - set(docs))
    if missing:
        raise SystemExit(f"DB 에 없는 자료: {missing}")
    empty = sorted(k for k, d in docs.items() if d["doc_kind"] == "DECISION" and not d["summary_chunk"])

    out = []
    for q in qids:
        if q not in pairs:
            continue
        top = rows[q]["top"]
        out.append({
            "query_id": q, "clause_ref": queries[q].get("clause_ref"), "query_text": queries[q]["query_text"],
            "is_control": q in CONTROLS,
            "candidates": [{"case_key": c, "rank_at_k20": top.index(c) + 1, **docs[c]} for c in pairs[q]],
        })
    n_eval = sum(len(x["candidates"]) for x in out if not x["is_control"])
    n_ctrl = sum(len(x["candidates"]) for x in out if x["is_control"])
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": TOPK_REPORT.name, "label_file": LABEL_V4.name,
        "config_note": f"{report['config']} K=20 (14+6). 상위 20 중 K=10 상위 10 에 없고 정답표(v4)에 행이 없는 자료",
        "label_guide": f"relevance 2 = 매우 관련, 1 = 관련, 0 = 무관 ({LABEL_V4.name} 와 같은 기준)",
        "counts": {"queries": len(out), "pairs": n_eval + n_ctrl, "pairs_eval": n_eval, "pairs_control": n_ctrl,
                   "by_doc_kind": {k: sum(1 for x in out for c in x["candidates"] if c["doc_kind"] == k)
                                   for k in ("CASE", "STANDARD", "DECISION")}},
        "problems": [f"{k}: DECISION_SUMMARY 청크 없음" for k in empty],
        "queries": out,
    }
    OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{OUT_FILE}: {json.dumps(data['counts'], ensure_ascii=False)}, 문제 {len(data['problems'])}, "
          f"{OUT_FILE.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
