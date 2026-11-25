"""검색 방식 평가 (정답: data/raw/_gold/label_sheet_final.csv). DB 는 읽기만 한다.

정답 기준
    relevance 1·2 = 정답, 0 또는 표에 없는 사례 = 오답 (nDCG 이득은 relevance 값 그대로: 2 는 가중치 2)
    정답이 없는 질문은 recall·MRR·nDCG 에서 빼고 '대조군'으로 상위 점수만 기록

설정 (모두 category='보험', 사례 단위, 상위 10)
    C 가중치      벡터/키워드 = 1.0/0.0, 0.8/0.2, 0.7/0.3, 0.6/0.4, 0.5/0.5  (원문 질문)
    확장 + C 0.7  LLM 확장문(쟁점 문장 1~2 + 핵심 용어 5~10)을 원문에 붙인 텍스트로 임베딩·키워드 검색
    확장 + C best 위 가중치 중 nDCG@10 이 가장 좋은 값 (동점이면 MRR, recall@10 순)

사례 순위 (search_probe.py 의 C 와 같음)
    벡터 상위 50 청크에 든 사례가 후보. 사례 점수 = w_v × (1 - 사례 최소 거리) + w_k × 사례 최대 word_similarity
    후보에 없는 사례는 순위 없음(찾지 못함).

지표
    recall@5, recall@10, MRR@10(10위 안 첫 정답의 역순위, 없으면 0), nDCG@10, 질문별 첫 정답 순위(전체 후보 기준)
    대조군: 질문별 1위 점수, 그리고 비교용으로 평가 질문의 1위 점수 평균

LLM 확장
    OpenAI chat completions, temperature 0, JSON 응답. 프롬프트에는 조항명과 조항 원문만 넣는다
    (정답 사례 제목·hint_cases 는 넣지 않음). 결과는 data/raw/_gold/expansions.json 에 캐시하고
    (질문 id, 조항 원문, 모델, 프롬프트 버전)이 같으면 다시 부르지 않는다.
    모델: 환경 변수 LLM_MODEL, 없으면 이 키로 쓸 수 있는 'gpt-<버전>-mini' 중 가장 최신.

검색 대상
    기본 실행은 CASE·STANDARD 청크만 쓴다 (DECISION 청크가 DB 에 들어온 뒤에도 이전 결과와 같은 조건).

결정례 평가 (--decision, LLM 확장 없음, 질문 임베딩만 호출)
    사례 키: CASE 'C'+key, STANDARD 'S'+key, DECISION 'D'+source_key (예: D64579, D64812-1)
    설정 3개, 모두 C 0.7/0.3 · category='보험' · 사례 단위 상위 10. 청크를 거른 뒤 같은 순위 방식(벡터 상위 50 청크 후보)
        a) CASE + STANDARD
        b) + DECISION (DECISION_CLAUSE 청크 제외)
        c) + DECISION (DECISION_CLAUSE 포함)
    라벨 없는 사례(그 질문의 정답표에 없는 사례)는 오답으로 계산하고, 설정별로 상위 10 중 라벨 없는 사례 수를 따로 기록.
    b·c 상위 10 의 라벨 없는 사례는 data/raw/_gold/label_delta.csv (label_sheet_final.csv 와 같은 컬럼.
    rank_B = 설정 b 순위, rank_C = 설정 c 순위, rank_A 빈칸, relevance 빈칸, (질문, 사례) 중복 제거)
    결과: data/raw/_report/retrieval_eval_decision.json

사용 (레포 루트에서):
    python scripts/collector/retrieval_eval.py
    python scripts/collector/retrieval_eval.py --decision
결과: data/raw/_report/retrieval_eval.json (키 값은 넣지 않음). 터미널에는 지표 요약 표만.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone

from collector import RAW_DIR, connect, load_env
from embedder import DEFAULT_DIMENSIONS, DEFAULT_MODEL, cost, masker, openai_key, to_vector_literal
from search_probe import CANDIDATE_CHUNKS, CATEGORY, SCORE_SQL

GOLD_DIR = RAW_DIR / "_gold"
QUERIES_FILE = GOLD_DIR / "gold_queries.json"
LABEL_FILE = GOLD_DIR / "label_sheet_final.csv"
CACHE_FILE = GOLD_DIR / "expansions.json"
REPORT_FILE = RAW_DIR / "_report" / "retrieval_eval.json"
DECISION_REPORT_FILE = RAW_DIR / "_report" / "retrieval_eval_decision.json"
DELTA_FILE = GOLD_DIR / "label_delta.csv"
LABEL_COLUMNS = ["query_id", "clause_ref", "case_key", "title", "rank_A", "rank_B", "rank_C", "is_hint", "relevance"]
BASE_KINDS = ("CASE", "STANDARD")
DECISION_CONFIGS = [  # (이름, 설명, 청크 거르기)
    ("a", "CASE + STANDARD", lambda c: c["doc_kind"] in BASE_KINDS),
    ("b", "+ DECISION (DECISION_CLAUSE 제외)", lambda c: c["chunk_type"] != "DECISION_CLAUSE"),
    ("c", "+ DECISION (DECISION_CLAUSE 포함)", lambda c: True),
]

TOP_K = 10
WEIGHTS = [(1.0, 0.0), (0.8, 0.2), (0.7, 0.3), (0.6, 0.4), (0.5, 0.5)]
EXPANSION_WEIGHT = (0.7, 0.3)
PREFIX = {"CASE": "C", "STANDARD": "S", "DECISION": "D"}

# USD / 1M 토큰 (input, output). OpenAI 공개 단가, 없으면 비용은 null
LLM_PRICES = {
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o-mini": (0.15, 0.60),
}
MINI_MODEL = re.compile(r"^gpt-(\d+(?:\.\d+)?)-mini$")

PROMPT_VERSION = "v1"
SYSTEM_PROMPT = "너는 한국 보험 약관과 금융감독원 분쟁조정 사례에 익숙한 보험 분쟁 전문가다."
USER_PROMPT = """아래 보험 약관 조항을 읽고, 이 조항이 문제가 되는 금융감독원 분쟁조정 사례를 검색하기 위한 확장 질의를 만들어라.

- issues: 분쟁조정 사례에서 쓰일 법한 쟁점 문장 1~2개 (예: "~가 약관상 ~에 해당하는지 여부")
- terms: 사례 본문에 나올 법한 핵심 용어 5~10개 (조항의 추상적 표현을 실제 치료·상품·행위 이름 같은 구체적인 말로 풀어쓴 것 포함)
- 특정 사례 번호나 사례 제목은 지어내지 말 것

JSON 으로만 답하라: {{"issues": ["..."], "terms": ["..."]}}

[조항] {clause_ref}
[조항 원문]
{query_text}"""


def case_key(doc_kind: str, source_key: str) -> str:
    return f"{PREFIX[doc_kind]}{source_key}"


# ---------------------------------------------------------------- 입력

def load_inputs(label_file=LABEL_FILE):
    queries = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))["queries"]
    gold: dict[str, dict[str, int]] = {q["id"]: {} for q in queries}
    with label_file.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rel = int(row["relevance"]) if row["relevance"].strip() else 0
            if rel > 0:
                gold.setdefault(row["query_id"], {})[row["case_key"]] = rel
    return queries, gold


# ---------------------------------------------------------------- LLM 확장

def resolve_llm_model(client) -> tuple[str, str]:
    if os.environ.get("LLM_MODEL"):
        return os.environ["LLM_MODEL"], "env LLM_MODEL"
    minis = [(m.created, m.id) for m in client.models.list() if MINI_MODEL.match(m.id)]
    if not minis:
        raise SystemExit("사용 가능한 gpt-*-mini 모델이 없습니다. LLM_MODEL 을 지정하세요")
    return max(minis)[1], "auto: 이 키로 쓸 수 있는 gpt-<버전>-mini 중 created 최신"


def cache_key(q: dict, model: str) -> str:
    raw = json.dumps([q["id"], q["query_text"], q.get("clause_ref", ""), model, PROMPT_VERSION], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def expand_all(client, queries: list[dict], model: str) -> tuple[dict[str, dict], dict]:
    cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
    usage = {"calls": 0, "cached": 0, "prompt_tokens": 0, "completion_tokens": 0, "resolved_models": set()}
    out = {}
    for q in queries:
        k = cache_key(q, model)
        if k in cache:
            usage["cached"] += 1
            out[q["id"]] = cache[k]
            continue
        res = client.chat.completions.create(
            model=model, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": USER_PROMPT.format(clause_ref=q.get("clause_ref", ""),
                                                                    query_text=q["query_text"])}])
        data = json.loads(res.choices[0].message.content)
        entry = {
            "query_id": q["id"], "model": model, "resolved_model": res.model, "prompt_version": PROMPT_VERSION,
            "issues": [str(x).strip() for x in data.get("issues", []) if str(x).strip()][:2],
            "terms": [str(x).strip() for x in data.get("terms", []) if str(x).strip()][:10],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        cache[k] = entry
        out[q["id"]] = entry
        usage["calls"] += 1
        usage["prompt_tokens"] += res.usage.prompt_tokens
        usage["completion_tokens"] += res.usage.completion_tokens
        usage["resolved_models"].add(res.model)
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")  # 호출마다 저장
    usage["resolved_models"] = sorted(usage["resolved_models"] | {e["resolved_model"] for e in out.values()})
    return out, usage


def expanded_text(q: dict, exp: dict) -> str:
    parts = [q["query_text"], *exp["issues"]]
    if exp["terms"]:
        parts.append("핵심 용어: " + ", ".join(exp["terms"]))
    return "\n".join(parts)


# ---------------------------------------------------------------- 검색

def embed_texts(client, texts: list[str]) -> tuple[list[list[float]], int]:
    vectors, tokens = [], 0
    for i in range(0, len(texts), 100):
        res = client.embeddings.create(model=DEFAULT_MODEL, input=texts[i:i + 100], dimensions=DEFAULT_DIMENSIONS)
        vectors += [d.embedding for d in sorted(res.data, key=lambda d: d.index)]
        tokens += res.usage.total_tokens
    return vectors, tokens


def score_chunks(conn, text: str, vec: list[float]) -> list[dict]:
    cur = conn.execute(SCORE_SQL, {"vec": to_vector_literal(vec), "query": text, "category": CATEGORY})
    cols = [d.name for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        r["distance"], r["keyword"] = float(r["distance"]), float(r["keyword"])
    return rows


def rank_cases(chunks: list[dict], w_vec: float, w_kw: float) -> list[dict]:
    """search_probe.py 의 C 와 같은 사례 순위 (가중치만 바꿈). 후보 사례 전체를 순위대로 반환."""
    by_dist = sorted(chunks, key=lambda c: (c["distance"], c["id"]))
    candidates = list(dict.fromkeys(c["dispute_case_id"] for c in by_dist[:CANDIDATE_CHUNKS]))
    by_case: dict[int, list[dict]] = {}
    for c in chunks:
        by_case.setdefault(c["dispute_case_id"], []).append(c)
    ranked = []
    for cid in candidates:
        cs = by_case[cid]
        sim = 1 - min(c["distance"] for c in cs)
        kw = max(c["keyword"] for c in cs)
        # 동점 처리도 search_probe 와 같게: 대표 청크(청크 단위 가중합 최대) id 순
        rep = max(cs, key=lambda c: (w_vec * (1 - c["distance"]) + w_kw * c["keyword"], -c["id"]))
        ranked.append({"case_key": case_key(cs[0]["doc_kind"], cs[0]["source_key"]), "title": cs[0]["title"],
                       "score": w_vec * sim + w_kw * kw, "vector_sim": sim, "keyword": kw, "_tie": rep["id"]})
    ranked.sort(key=lambda r: (-r["score"], r["_tie"]))
    return ranked


# ---------------------------------------------------------------- 지표

def metrics(ranking: list[str], rels: dict[str, int]) -> dict:
    top = ranking[:TOP_K]
    hits5 = sum(1 for k in top[:5] if k in rels)
    hits10 = sum(1 for k in top if k in rels)
    first = next((i for i, k in enumerate(ranking, 1) if k in rels), None)
    dcg = sum(rels.get(k, 0) / math.log2(i + 1) for i, k in enumerate(top, 1))
    ideal = sorted(rels.values(), reverse=True)[:TOP_K]
    idcg = sum(g / math.log2(i + 1) for i, g in enumerate(ideal, 1))
    return {
        "recall@5": hits5 / len(rels), "recall@10": hits10 / len(rels),
        "mrr@10": 1 / first if first and first <= TOP_K else 0.0,
        "ndcg@10": dcg / idcg if idcg else 0.0,
        "first_relevant_rank": first, "relevant": len(rels), "hits@10": hits10,
        "found_in_candidates": sum(1 for k in rels if k in ranking),
    }


def evaluate(name: str, desc: str, rankings: dict[str, list[dict]], gold: dict, control_ids: list[str]) -> dict:
    per_query, controls, eval_top1 = {}, {}, []
    for qid, ranked in rankings.items():
        keys = [r["case_key"] for r in ranked]
        top5 = [{"rank": i, "case_key": r["case_key"], "title": r["title"], "score": round(r["score"], 4),
                 "vector_sim": round(r["vector_sim"], 4), "keyword": round(r["keyword"], 4)}
                for i, r in enumerate(ranked[:5], 1)]
        if qid in control_ids:
            controls[qid] = {"top1_score": top5[0]["score"] if top5 else None, "top5": top5}
            continue
        m = metrics(keys, gold[qid])
        m["top10"] = [{"rank": i, "case_key": r["case_key"], "score": round(r["score"], 4),
                       "relevance": gold[qid].get(r["case_key"], 0)} for i, r in enumerate(ranked[:TOP_K], 1)]
        per_query[qid] = m
        if top5:
            eval_top1.append(top5[0]["score"])
    n = len(per_query)
    mean = lambda key: round(sum(m[key] for m in per_query.values()) / n, 4)  # noqa: E731
    ctrl_scores = [c["top1_score"] for c in controls.values() if c["top1_score"] is not None]
    return {
        "name": name, "description": desc,
        "summary": {"queries": n, "recall@5": mean("recall@5"), "recall@10": mean("recall@10"),
                    "mrr@10": mean("mrr@10"), "ndcg@10": mean("ndcg@10"),
                    "no_hit@10": sum(1 for m in per_query.values() if m["hits@10"] == 0),
                    "control_top1_mean": round(sum(ctrl_scores) / len(ctrl_scores), 4) if ctrl_scores else None,
                    "eval_top1_mean": round(sum(eval_top1) / len(eval_top1), 4) if eval_top1 else None},
        "first_relevant_rank": {q: m["first_relevant_rank"] for q, m in per_query.items()},
        "per_query": per_query, "controls": controls,
    }


# ---------------------------------------------------------------- 결정례 평가 (--decision)

def load_labeled_keys(label_file=LABEL_FILE) -> dict[str, set[str]]:
    """질문별로 정답표에 있는 사례 키 (relevance 0 포함 = 라벨이 매겨진 사례)."""
    labeled: dict[str, set[str]] = {}
    with label_file.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            labeled.setdefault(row["query_id"], set()).add(row["case_key"])
    return labeled


def eval_decision() -> None:
    import openai

    queries, gold = load_inputs()
    labeled = load_labeled_keys()
    eval_ids = [q["id"] for q in queries if gold.get(q["id"])]
    control_ids = [q["id"] for q in queries if not gold.get(q["id"])]
    w_vec, w_kw = EXPANSION_WEIGHT  # C 0.7 / 0.3

    key = openai_key()
    if not key:
        raise SystemExit("OPENAI_API_KEY 가 .env 와 환경 변수에 없습니다")
    mask = masker(key)
    client = openai.OpenAI(api_key=key, max_retries=3, timeout=120)
    try:
        vecs, emb_tokens = embed_texts(client, [q["query_text"] for q in queries])
    except openai.APIError as e:
        raise SystemExit(mask(f"API 실패: {type(e).__name__} {getattr(e, 'status_code', '')}")) from None

    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")  # DB 쓰기 금지
    chunks = {q["id"]: score_chunks(conn, q["query_text"], v) for q, v in zip(queries, vecs)}
    pool = dict(conn.execute("""SELECT chunk_type, count(*) FROM case_chunk c JOIN dispute_case d ON d.id = c.dispute_case_id
                                WHERE d.category = %s AND c.embedding IS NOT NULL GROUP BY 1 ORDER BY 1""",
                             (CATEGORY,)).fetchall())
    conn.close()

    results, rankings_by_config = [], {}
    for name, desc, keep in DECISION_CONFIGS:
        rankings = {qid: rank_cases([c for c in ch if keep(c)], w_vec, w_kw) for qid, ch in chunks.items()}
        rankings_by_config[name] = rankings
        r = evaluate(f"{name}) C {w_vec}/{w_kw}", desc, rankings, gold, control_ids)
        unl = {qid: [x["case_key"] for x in rankings[qid][:TOP_K] if x["case_key"] not in labeled.get(qid, set())]
               for qid in rankings}
        dec = {qid: [x["case_key"] for x in rankings[qid][:TOP_K] if x["case_key"].startswith("D")] for qid in rankings}
        r["summary"].update({
            "unlabeled_in_top10_eval": sum(len(unl[q]) for q in eval_ids),
            "unlabeled_in_top10_eval_mean": round(sum(len(unl[q]) for q in eval_ids) / len(eval_ids), 2),
            "unlabeled_in_top10_control": sum(len(unl[q]) for q in control_ids),
            "decision_in_top10_eval": sum(len(dec[q]) for q in eval_ids),
            "control_top1": {q: r["controls"][q]["top1_score"] for q in control_ids},
        })
        r["unlabeled_top10"] = {q: v for q, v in unl.items() if v}
        r["decision_top10"] = {q: v for q, v in dec.items() if v}
        for q in control_ids:
            r["controls"][q]["top10"] = [{"rank": i, "case_key": x["case_key"], "title": x["title"],
                                          "score": round(x["score"], 4)}
                                         for i, x in enumerate(rankings[q][:TOP_K], 1)]
        results.append(r)

    # 질문별 첫 정답 순위 비교표
    first_rank = {q: {r["name"][0]: r["first_relevant_rank"][q] for r in results} for q in eval_ids}
    changed = {q: v for q, v in first_rank.items() if len(set(v.values())) > 1}

    # label_delta.csv: b·c 상위 10 의 라벨 없는 사례 (질문·사례 중복 제거)
    qmap = {q["id"]: q for q in queries}
    delta: dict[tuple[str, str], dict] = {}
    for name, col in (("b", "rank_B"), ("c", "rank_C")):
        for qid, ranked in rankings_by_config[name].items():
            for i, x in enumerate(ranked[:TOP_K], 1):
                if x["case_key"] in labeled.get(qid, set()):
                    continue
                row = delta.setdefault((qid, x["case_key"]), {
                    "query_id": qid, "clause_ref": qmap[qid].get("clause_ref", ""), "case_key": x["case_key"],
                    "title": x["title"], "rank_A": "", "rank_B": "", "rank_C": "",
                    "is_hint": 1 if x["case_key"] in (qmap[qid].get("hint_cases") or []) else 0, "relevance": ""})
                row[col] = i
    order = {q["id"]: n for n, q in enumerate(queries)}
    delta_rows = sorted(delta.values(), key=lambda r: (order[r["query_id"]], min(
        v for v in (r["rank_B"], r["rank_C"]) if v != ""), r["case_key"]))
    with DELTA_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_COLUMNS)
        w.writeheader()
        w.writerows(delta_rows)

    emb_cost = cost(emb_tokens, DEFAULT_MODEL)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_file": str(LABEL_FILE.relative_to(RAW_DIR.parent.parent)),
        "category": CATEGORY, "top_k": TOP_K, "candidate_chunks": CANDIDATE_CHUNKS,
        "weights": {"vector": w_vec, "keyword": w_kw}, "embedding_model": DEFAULT_MODEL,
        "chunk_pool": pool,
        "configs": {n: d for n, d, _ in DECISION_CONFIGS},
        "eval_queries": eval_ids, "control_queries": control_ids,
        "usage": {"embedding_tokens": emb_tokens, "embedding_cost_usd": emb_cost},
        "notes": [
            "라벨 없는 사례(그 질문의 정답표에 없는 사례)는 오답으로 계산. 결정례(D)는 아직 라벨이 하나도 없으므로 "
            "b·c 의 지표는 결정례가 정답이어도 오르지 않고, 결정례가 상위로 올라와 정답 C·S 를 밀어내면 내려간다 (하한 추정치)",
            "후보는 설정별로 거른 청크 중 벡터 상위 50 청크에 든 사례",
            f"label_delta.csv: b·c 상위 10 의 라벨 없는 사례 {len(delta_rows)}행 (평가·대조군 질문 모두). "
            "rank_B=설정 b 순위, rank_C=설정 c 순위, rank_A 는 비움",
        ],
        "summary_table": [{"config": r["name"], **{k: r["summary"][k] for k in (
            "recall@5", "recall@10", "mrr@10", "ndcg@10", "no_hit@10", "unlabeled_in_top10_eval",
            "unlabeled_in_top10_eval_mean", "decision_in_top10_eval", "control_top1_mean", "eval_top1_mean")}}
            for r in results],
        "first_relevant_rank": first_rank,
        "first_relevant_rank_changed": changed,
        "label_delta": {"file": str(DELTA_FILE.relative_to(RAW_DIR.parent.parent)), "rows": len(delta_rows),
                        "by_prefix": {p: sum(1 for r in delta_rows if r["case_key"].startswith(p)) for p in "CSD"}},
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert key not in text
    DECISION_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    DECISION_REPORT_FILE.write_text(text, encoding="utf-8")

    header = (f"{'설정':<44}{'R@5':>7}{'R@10':>7}{'MRR':>7}{'nDCG':>7}{'무적중':>6}{'무라벨':>6}{'D수':>5}"
              f"{'대조1위':>8}{'평가1위':>8}")
    print(header)
    print("-" * len(header))
    for r in results:
        s = r["summary"]
        print(f"{r['name'] + ' ' + r['description']:<44}{s['recall@5']:>7.3f}{s['recall@10']:>7.3f}{s['mrr@10']:>7.3f}"
              f"{s['ndcg@10']:>7.3f}{s['no_hit@10']:>6}{s['unlabeled_in_top10_eval']:>6}{s['decision_in_top10_eval']:>5}"
              f"{s['control_top1_mean']:>8.3f}{s['eval_top1_mean']:>8.3f}")
    print(f"\n첫 정답 순위가 바뀐 질문 {len(changed)}개 | label_delta {len(delta_rows)}행 | "
          f"토큰 {emb_tokens:,} | 비용 ${emb_cost:.6f}")


# ---------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description="검색 방식 평가 (DB 읽기 전용)")
    parser.add_argument("--decision", action="store_true", help="결정례 추가 효과 평가 (설정 a·b·c)")
    parser.add_argument("--mix", action="store_true",
                        help="결정례 섞는 방식 비교 (설정 a·b·d·e·f, 정답 label_sheet_final_v2.csv)")
    parser.add_argument("--mix2", action="store_true",
                        help="종류별 후보 분리 비교 (설정 a·e·f·g·h, 정답 label_sheet_final_v2.csv)")
    args = parser.parse_args()
    if args.mix2:
        from retrieval_mix import eval_mix2
        eval_mix2()
        return
    if args.decision:
        eval_decision()
        return
    if args.mix:
        from retrieval_mix import eval_mix
        eval_mix()
        return
    import openai

    queries, gold = load_inputs()
    eval_ids = [q["id"] for q in queries if gold.get(q["id"])]
    control_ids = [q["id"] for q in queries if not gold.get(q["id"])]

    key = openai_key()
    if not key:
        raise SystemExit("OPENAI_API_KEY 가 .env 와 환경 변수에 없습니다")
    mask = masker(key)
    client = openai.OpenAI(api_key=key, max_retries=3, timeout=120)
    try:
        llm_model, llm_model_source = resolve_llm_model(client)
        expansions, llm_usage = expand_all(client, queries, llm_model)
        texts_orig = [q["query_text"] for q in queries]
        texts_exp = [expanded_text(q, expansions[q["id"]]) for q in queries]
        vecs, emb_tokens = embed_texts(client, texts_orig + texts_exp)
    except openai.APIError as e:
        raise SystemExit(mask(f"API 실패: {type(e).__name__} {getattr(e, 'status_code', '')}")) from None
    vec_orig, vec_exp = vecs[:len(queries)], vecs[len(queries):]

    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")  # DB 쓰기 금지
    base = lambda rows: [c for c in rows if c["doc_kind"] in BASE_KINDS]  # noqa: E731  DECISION 이 들어오기 전과 같은 조건
    chunks_orig = {q["id"]: base(score_chunks(conn, t, v)) for q, t, v in zip(queries, texts_orig, vec_orig)}
    chunks_exp = {q["id"]: base(score_chunks(conn, t, v)) for q, t, v in zip(queries, texts_exp, vec_exp)}
    conn.close()

    results = []
    for wv, wk in WEIGHTS:
        rankings = {qid: rank_cases(ch, wv, wk) for qid, ch in chunks_orig.items()}
        results.append(evaluate(f"C {wv}/{wk}", f"원문 질문, 벡터 {wv} / 키워드 {wk}", rankings, gold, control_ids))
    best = max(results, key=lambda r: (r["summary"]["ndcg@10"], r["summary"]["mrr@10"], r["summary"]["recall@10"]))
    best_w = WEIGHTS[results.index(best)]
    for (wv, wk), label in ((EXPANSION_WEIGHT, "확장 + C"), (best_w, "확장 + C best")):
        rankings = {qid: rank_cases(ch, wv, wk) for qid, ch in chunks_exp.items()}
        results.append(evaluate(f"{label} {wv}/{wk}", f"원문 + LLM 확장문, 벡터 {wv} / 키워드 {wk}",
                                rankings, gold, control_ids))

    llm_price = LLM_PRICES.get(llm_model)
    llm_cost = (round(llm_usage["prompt_tokens"] / 1e6 * llm_price[0]
                      + llm_usage["completion_tokens"] / 1e6 * llm_price[1], 6) if llm_price else None)
    emb_cost = cost(emb_tokens, DEFAULT_MODEL)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_file": str(LABEL_FILE.relative_to(RAW_DIR.parent.parent)),
        "category": CATEGORY, "top_k": TOP_K, "candidate_chunks": CANDIDATE_CHUNKS,
        "eval_queries": eval_ids, "control_queries": control_ids,
        "best_weight_from_part1": {"weights": list(best_w), "criterion": "nDCG@10 → MRR@10 → recall@10"},
        "models": {"embedding": DEFAULT_MODEL, "llm": llm_model, "llm_source": llm_model_source,
                   "llm_resolved": llm_usage["resolved_models"], "llm_temperature": 0,
                   "prompt_version": PROMPT_VERSION},
        "usage": {
            "embedding_tokens": emb_tokens, "embedding_cost_usd": emb_cost,
            "llm_calls": llm_usage["calls"], "llm_cached": llm_usage["cached"],
            "llm_prompt_tokens": llm_usage["prompt_tokens"], "llm_completion_tokens": llm_usage["completion_tokens"],
            "llm_price_per_1m": list(llm_price) if llm_price else None, "llm_cost_usd": llm_cost,
            "total_cost_usd": round(emb_cost + (llm_cost or 0), 6),
        },
        "prompt": {"system": SYSTEM_PROMPT, "user_template": USER_PROMPT},
        "expansions": {q["id"]: {"issues": expansions[q["id"]]["issues"], "terms": expansions[q["id"]]["terms"]}
                       for q in queries},
        "notes": [
            "정답 라벨은 원문 질문의 A/B/C 상위 10 + 힌트에서만 매겼으므로, 확장 검색이 새로 찾은 라벨 없는 사례는 오답으로 계산됨",
            "후보는 벡터 상위 50 청크에 든 사례뿐 (found_in_candidates 가 relevant 보다 작으면 그 정답은 어떤 가중치로도 못 찾음)",
        ],
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert key not in text
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(text, encoding="utf-8")

    header = f"{'설정':<22}{'R@5':>7}{'R@10':>7}{'MRR':>7}{'nDCG':>7}{'무적중':>6}{'대조1위':>8}{'평가1위':>8}"
    print(header)
    print("-" * len(header))
    for r in results:
        s = r["summary"]
        print(f"{r['name']:<22}{s['recall@5']:>7.3f}{s['recall@10']:>7.3f}{s['mrr@10']:>7.3f}{s['ndcg@10']:>7.3f}"
              f"{s['no_hit@10']:>6}{s['control_top1_mean']:>8.3f}{s['eval_top1_mean']:>8.3f}")
    print(f"\n평가 {len(eval_ids)}개, 대조군 {len(control_ids)}개 ({', '.join(control_ids)}) | LLM {llm_model} | "
          f"토큰 임베딩 {emb_tokens:,} / LLM {llm_usage['prompt_tokens']:,}+{llm_usage['completion_tokens']:,} "
          f"(호출 {llm_usage['calls']}, 캐시 {llm_usage['cached']}) | 비용 ${report['usage']['total_cost_usd']:.4f}")


if __name__ == "__main__":
    main()
