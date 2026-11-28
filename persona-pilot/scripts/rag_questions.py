"""RAG 기반 검증 질문 만들기 (2026-11-28, SPEC.md 8.2 · 8.3 을 파일럿에서 재현).

흐름: 약관 조항 → 분쟁 자료 20건 검색 (사례·해결기준 14 + 결정례 6) → LLM 이 실제 분쟁 오해(complaint)로
      3지선다 질문을 만든다 → c_validate 가 읽는 케이스 폴더(results_valid/<case>/)에 저장.

검색은 sona-server/scripts/collector 의 함수(score_chunks · rank_cases · rank_split)를 그대로 불러 쓴다 (팀 방식과 같게).
개념 태그 보정은 SPEC 8.2-4 에 따라 생략한다. DB 는 읽기만 한다 (로컬 Docker DB, sona-server/.env 의 POSTGRES_*).
임베딩은 text-embedding-3-small(1536), 키는 persona-pilot/.env 의 OPENAI_API_KEY.

  search   : 조항별 분쟁 자료 20건 → search.json
  generate : 조항별 질문 생성 (LLM) → questions_raw.json, facts.json, options.json, document.txt
실행: python scripts/rag_questions.py all --case dy_rag
"""

import argparse
import importlib.util
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
COLLECTOR = Path("C:/WON_academy_Final_project/sona-server/scripts/collector")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(COLLECTOR))

from common_llm import load_dotenv, oa_client  # noqa: E402


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# 동양생명 암치료보험: 상품설명서(guide_only)에 다뤄지는 조항
DY_CLAUSES = [7, 8, 11, 12, 28, 40]
N_BASE, N_DEC = 14, 6
FIELD_CHARS = 350  # 자료 칸별로 LLM 에 넘기는 글자 수


def case_dir(case):
    d = ROOT / "results_valid" / case
    d.mkdir(parents=True, exist_ok=True)
    return d


def dy_clauses():
    mat = load("build_materials", "02_build_materials.py")
    arts = mat.split_articles(mat.load_main_terms())
    out = []
    for n in DY_CLAUSES:
        text = arts[n]
        title = re.search(r"【([^】]+)】", text)
        out.append({"clause_id": f"제{n}조", "title": title.group(1) if title else "", "text": text})
    return out


def stage_search(case):
    from collector import connect, load_env
    from embedder import DEFAULT_DIMENSIONS, DEFAULT_MODEL
    from retrieval_eval import BASE_KINDS, case_key, rank_cases, score_chunks
    from retrieval_mix import by_score, rank_split

    load_dotenv()
    clauses = dy_clauses()
    res = oa_client().embeddings.create(model=DEFAULT_MODEL, input=[c["text"] for c in clauses],
                                        dimensions=DEFAULT_DIMENSIONS)
    vecs = [d.embedding for d in sorted(res.data, key=lambda d: d.index)]
    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")  # DB 쓰기 금지
    by_key = {}
    for row in conn.execute("""SELECT id, doc_kind, source_key, title, complaint, dispute_issue, decision_reason,
                                      consumer_warning FROM dispute_case WHERE category = '보험'"""):
        cid, kind, skey, title, complaint, issue, reason, warn = row
        by_key[case_key(kind, skey)] = {"id": cid, "doc_kind": kind, "title": title, "complaint": complaint or "",
                                        "dispute_issue": issue or "", "decision_reason": reason or "",
                                        "consumer_warning": warn or ""}
    out = []
    for c, v in zip(clauses, vecs):
        chunks = [x for x in score_chunks(conn, c["text"], v) if x["chunk_type"] != "DECISION_CLAUSE"]
        cs = [x for x in chunks if x["doc_kind"] in BASE_KINDS]
        dec = [x for x in chunks if x["doc_kind"] == "DECISION"]
        ranked = rank_split(by_score(rank_cases(cs, 0.7, 0.3) + rank_cases(dec, 0.7, 0.3)), [], c["clause_id"],
                            N_BASE, N_DEC)[:N_BASE + N_DEC]
        out.append({"clause_id": c["clause_id"], "clause_title": c["title"],
                    "cases": [{"case_key": r["case_key"], "score": round(r["score"], 4), **by_key[r["case_key"]]}
                              for r in ranked]})
        print(c["clause_id"], c["title"], "→", len(out[-1]["cases"]), "건 |",
              " / ".join(x["title"][:20] for x in out[-1]["cases"][:3]))
    conn.close()
    (case_dir(case) / "search.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 질문 만들기 (SPEC 8.3)
Q_SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "items": {
    "type": "object", "properties": {
        "question": {"type": "string"},
        "correct": {"type": "string"},
        "wrong": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "critical": {"type": "boolean"}, "from_case": {"type": "string"}},
            "required": ["text", "critical", "from_case"], "additionalProperties": False}},
        "answer_reason": {"type": "string"},
        "guide_quote": {"type": "string"},
        "key_phrases": {"type": "array", "items": {"type": "string"}},
        "evidence_cases": {"type": "array", "items": {"type": "string"}}},
    "required": ["question", "correct", "wrong", "answer_reason", "guide_quote", "key_phrases", "evidence_cases"],
    "additionalProperties": False}}}, "required": ["questions"], "additionalProperties": False}

Q_PROMPT = """보험 상품설명서의 오해 소지를 검사하기 위한 3지선다 검증 질문을 만드세요.

[약관 조항] {clause_id} {clause_title}
{clause_text}

[이 조항으로 찾은 금감원 분쟁 자료 {n}건]
- 20건 중 상당수는 이 조항과 관련이 없습니다. **조항과 관련 없는 자료는 무시하세요.**
- complaint 는 소비자가 실제로 믿은 것, decision_reason 은 실제 판단입니다.
{cases}

[소비자가 읽는 상품설명서]
{guide}

만들 것: 이 조항에 대해 질문 0~2개 (관련 분쟁 자료가 없으면 0개).
- 질문은 위 **상품설명서만 읽고 답할 수 있어야** 합니다. guide_quote 에 정답 근거 문장을 설명서에서 글자 그대로 옮기세요.
- 누구나 아는 결론(예: 갱신하면 보험료가 오를 수 있다)이 아니라, 설명서에만 있는 **조건·시점·예외·대상·금액**을 묻습니다.
- correct: 정답 보기 1개. wrong: 오답 보기 정확히 2개. 오답은 관련 분쟁 자료의 complaint(소비자가 믿은 것)에서 가져온
  **실제로 분쟁이 난 오해**로 쓰고, from_case 에 그 자료의 case_key 를 적으세요 (근거 자료가 없으면 빈 문자열).
- critical = 실제보다 더 많이 받거나 없는 보장·권리를 있다고 믿는 오해이면 true.
- 세 보기 모두 20~40자, 같은 문장 구조·같은 말투. 정답만 길거나 자세하거나 신중해 보이면 안 됩니다.
- key_phrases: 정답 근거가 되는 설명서 문구 1~3개, 설명서에 적힌 글자 그대로 (각 4~20자).
- evidence_cases: 질문의 근거로 쓴 분쟁 자료 case_key 목록."""


def fmt_cases(cases):
    def cut(s):
        s = re.sub(r"\s+", " ", s or "").strip()
        return s[:FIELD_CHARS] + ("…" if len(s) > FIELD_CHARS else "")
    return "\n".join(f"({c['case_key']}) {c['title']}\n  complaint: {cut(c['complaint'])}\n"
                     f"  dispute_issue: {cut(c['dispute_issue'])}\n  decision_reason: {cut(c['decision_reason'])}"
                     for c in cases)


def stage_generate(case):
    bm = load("b_modu_style", "b_modu_style.py")
    d = case_dir(case)
    search = json.loads((d / "search.json").read_text(encoding="utf-8"))
    guide = json.loads((ROOT / "results_c" / "path_docs.json").read_text(encoding="utf-8"))["guide_only"]["text"]
    clauses = {c["clause_id"]: c for c in dy_clauses()}
    compact = guide.replace(" ", "")
    raw, facts, options = [], [], []
    for s in search:
        c = clauses[s["clause_id"]]
        prompt = Q_PROMPT.format(clause_id=c["clause_id"], clause_title=c["title"], clause_text=c["text"],
                                 n=len(s["cases"]), cases=fmt_cases(s["cases"]), guide=guide)
        out = bm.call_json(prompt, f"rag_question:{case}:{c['clause_id']}", Q_SCHEMA, thinking="adaptive",
                           effort="medium", max_tokens=6000)
        for q in out["questions"]:
            quote_ok = q["guide_quote"].replace(" ", "")[:30] in compact
            raw.append({"clause_id": c["clause_id"], "quote_in_guide": quote_ok, **q})
            if not quote_ok or len(q["wrong"]) < 2:
                print("  제외 (설명서 근거 없음 또는 보기 부족):", q["question"][:40])
                continue
            fid = f"R{len(facts) + 1}"
            phrases = [k for k in q["key_phrases"] if k.strip() and k.replace(" ", "") in compact]
            facts.append({"fact_id": fid, "category": c["clause_id"] + " " + c["title"], "importance": 1,
                          "question": q["question"], "answer": q["correct"] + " (" + q["answer_reason"] + ")",
                          "units": [re.escape(p).replace(r"\ ", r"\s?") for p in phrases]
                          or [re.escape(q["correct"][:6])],
                          "evidence_cases": q["evidence_cases"],
                          "wrong_from_cases": [w["from_case"] for w in q["wrong"][:2]]})
            opts = [{"text": q["correct"], "correct": True, "critical": False}] + \
                   [{"text": w["text"], "correct": False, "critical": w["critical"]} for w in q["wrong"][:2]]
            random.Random(fid).shuffle(opts)
            for k, o in zip("ABC", opts):
                o["key"] = k
            options.append({"fact_id": fid, "options": opts})
            print(f"{fid} [{c['clause_id']}] {q['question']}")
    (d / "questions_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "options.json").write_text(json.dumps(options, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "document.txt").write_text(guide, encoding="utf-8")
    print("질문", len(facts), "개 저장 →", d)


# ---------------------------------------------------------------- 보기 다시 쓰기 (찍기 검사 통과용)
# 1차 결과 (2026-11-28): 실제 분쟁 오해는 거의 '더 받는다' 쪽이라 정답이 늘 '덜 주는(신중한)' 보기 → 읽지 않고 87~97% 정답.
# 그래서 오답 하나는 실제 분쟁 오해(더 받는다), 다른 하나는 반대 방향(실제보다 덜 받는다·더 불리하다) 오해로 다시 쓴다.
R_SCHEMA = {"type": "object", "properties": {
    "correct": {"type": "string"},
    "wrong_case": {"type": "string"}, "wrong_case_critical": {"type": "boolean"},
    "wrong_opposite": {"type": "string"}},
    "required": ["correct", "wrong_case", "wrong_case_critical", "wrong_opposite"], "additionalProperties": False}

R_PROMPT = """아래 3지선다 검증 질문의 보기를 다시 쓰세요. 설명서를 읽지 않은 사람이 보기 문장만 보고 정답을 알아채면 안 됩니다.
지금 보기는 정답만 '덜 주는·신중한' 쪽이라 읽지 않고도 {rate}가 정답을 골랐습니다.

[질문] {question}
[정답 내용] {answer}
[실제 분쟁에서 소비자가 믿은 오해] {complaint_wrong}

- correct: 정답 내용과 같은 뜻.
- wrong_case: 실제 분쟁 오해를 그대로 살린 오답 (보통 실제보다 더 받는다고 믿는 쪽).
- wrong_opposite: 반대 방향 오답 — 실제보다 **덜 받거나 더 불리하다고** 믿는 그럴듯한 오해. 설명서에 나오는 다른 숫자·기간·조건을 섞으세요.
- 세 보기 모두 같은 문장 구조, 같은 길이(20~40자), 같은 확신 정도. '예/아니요'로 시작하지 마세요.
  셋 중 어느 것도 '가장 신중해 보이는 보기'가 되면 안 됩니다."""


def stage_refine(case, limit=0.4, rounds=2):
    bm = load("b_modu_style", "b_modu_style.py")
    v = load("c_validate", "c_validate.py")
    d, _ = v.setup(case)
    t = v.t
    raw = {q["question"]: q for q in json.loads((d / "questions_raw.json").read_text(encoding="utf-8"))}
    rates = json.loads((d / "guess.json").read_text(encoding="utf-8")) if (d / "guess.json").exists() else t.guess_rates(30)
    for r in range(rounds):
        bad = [f for f in t.FACTS if rates[f["fact_id"]] > limit]
        if not bad:
            break
        for f in bad:
            q = raw[f["question"]]
            out = bm.call_json(R_PROMPT.format(rate=f"{rates[f['fact_id']]:.0%}", question=f["question"], answer=f["answer"],
                                               complaint_wrong=" / ".join(w["text"] for w in q["wrong"])),
                               f"rag_refine:{case}:{f['fact_id']}", R_SCHEMA, thinking="adaptive", effort="medium",
                               max_tokens=3000)
            opts = [{"text": out["correct"], "correct": True, "critical": False},
                    {"text": out["wrong_case"], "correct": False, "critical": out["wrong_case_critical"]},
                    {"text": out["wrong_opposite"], "correct": False, "critical": False}]
            random.Random(f["fact_id"] + str(r)).shuffle(opts)
            for k, o in zip("ABC", opts):
                o["key"] = k
            t.OPTS[f["fact_id"]] = opts
        t.OPT_FILE.write_text(json.dumps([{"fact_id": k, "options": v_} for k, v_ in sorted(t.OPTS.items())],
                                         ensure_ascii=False, indent=1), encoding="utf-8")
        new = t.guess_rates(30)
        rates = {k: (new[k] if k in {f["fact_id"] for f in bad} else rates[k]) for k in rates}
        print(f"[{r + 1}회차] 찍기:", {k: f"{x:.0%}" for k, x in rates.items()}, flush=True)
    (d / "guess.json").write_text(json.dumps(rates, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in t.FACTS:
        print(f["fact_id"], " | ".join(f"{o['key']}{'*' if o['correct'] else ''}{'!' if o['critical'] else ''} {o['text']}"
                                       for o in t.OPTS[f["fact_id"]]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["search", "generate", "refine", "all"])
    ap.add_argument("--case", default="dy_rag")
    a = ap.parse_args()
    if a.stage == "refine":
        sys.argv = sys.argv[:1]
        stage_refine(a.case)
        raise SystemExit
    if a.stage in ("search", "all"):
        stage_search(a.case)
    if a.stage in ("generate", "all"):
        stage_generate(a.case)
