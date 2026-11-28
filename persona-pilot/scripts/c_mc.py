"""객관식 vs 서술형 비교 (2026-11-27). C안 v4 의 같은 메모(3회분)로 '답하는 형식'만 객관식으로 바꿔 답하게 한다.

  options  : 6문항마다 보기 4개 (정답 1 · 소비자가 흔히 하는 오해 2 · 모르겠다 1) 를 AI 가 한 번 만들고 고정
  answer   : results_c / results_c_rep2 / results_c_rep3 의 메모로 객관식 답 (채점은 코드가 정답 비교)
  baseline : 메모 없이(읽지 않음) 객관식 10회 → 찍어서 맞히는 정도
  compare  : 서술형 결과와 비교 → results_mc/compare.md
실행: python scripts/c_mc.py all
"""

import argparse
import importlib.util
import json
import random
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results_mc"
REPS = ["results_c", "results_c_rep2", "results_c_rep3"]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


bm = load("b_modu_style", "b_modu_style.py")
ch = load("c_hybrid", "c_hybrid.py")
FACTS = json.loads((ROOT / "results_b" / "facts.json").read_text(encoding="utf-8"))
FMAP = {f["fact_id"]: f for f in FACTS}
TOT_W = sum(f["importance"] for f in FACTS)
DONT_KNOW = "모르겠다"


def jload(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]


def jdump(p, rows):
    Path(p).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


# ---------- 보기 만들기 ----------
OPT_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {
        "fact_id": {"type": "string"}, "correct": {"type": "string"},
        "wrong": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "critical": {"type": "boolean"}},
            "required": ["text", "critical"], "additionalProperties": False}}},
    "required": ["fact_id", "correct", "wrong"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}

OPT_PROMPT = """아래 보험 상품설명서와 문항마다, 객관식 보기를 만드세요.
- correct: 문서 기준 정답을 짧은 보기 문장으로 (기준 답과 같은 뜻)
- wrong: 일반 소비자가 실제로 할 법한 그럴듯한 오해 보기 정확히 2개.
- 정답과 오답 3개 모두 **20~35자**, 같은 문장 구조로 쓰세요. 정답만 길거나 자세하거나 조건을 더 붙이면 안 됩니다
  (길이·자세함으로 정답을 알아챌 수 없어야 합니다).
  critical = 그 보기가 실제보다 더 많이 받거나 없는 보장·권리를 있다고 믿는 오해이면 true
- '모르겠다' 보기는 만들지 마세요 (코드가 붙입니다).

[문항과 기준 답]
{facts}

[상품설명서]
{doc}"""


def stage_options():
    facts = "\n".join(f"{f['fact_id']}. {f['question']}\n   기준 답: {f['answer']}" for f in FACTS)
    d = bm.call_json(OPT_PROMPT.format(facts=facts, doc=bm.document()), "mc_options", OPT_SCHEMA, **bm.STRONG)
    out = []
    for it in d["items"]:
        opts = [{"text": it["correct"], "correct": True, "critical": False}] + \
               [{"text": w["text"], "correct": False, "critical": w["critical"]} for w in it["wrong"][:2]]
        random.Random(it["fact_id"]).shuffle(opts)          # 정답 위치를 문항마다 고정된 무작위로
        opts.append({"text": DONT_KNOW, "correct": False, "critical": False})
        for k, o in zip("ABCD", opts):
            o["key"] = k
        out.append({"fact_id": it["fact_id"], "options": opts})
    (OUT / "options.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for it in out:
        print(it["fact_id"], " | ".join(f"{o['key']}{'*' if o['correct'] else ''}{'!' if o['critical'] else ''} {o['text']}"
                                       for o in it["options"]))


# ---------- 객관식으로 답하기 ----------
ANS_SCHEMA = {"type": "object", "properties": {"answers": {"type": "array", "items": {
    "type": "object", "properties": {"fact_id": {"type": "string"}, "choice": {"type": "string", "enum": list("ABCD")}},
    "required": ["fact_id", "choice"], "additionalProperties": False}}},
    "required": ["answers"], "additionalProperties": False}

ANS_PROMPT = """{card}

조금 전 보험 상품설명서를 읽었고, 지금은 설명서를 다시 볼 수 없습니다.
설명서를 읽고 머릿속에 남은 것은 아래가 전부입니다.

[머릿속에 남은 것]
{memory}

창구 직원이 아래 질문을 하며 보기를 보여 줍니다. 머릿속에 남은 것을 떠올리며 이 사람이 고를 보기를 하나씩 고르세요.
남은 것에 없는 내용은 이 사람이 떠올릴 법한 생각대로 고르고, 전혀 모르겠으면 '모르겠다'를 고르세요.

[질문과 보기]
{questions}"""


def options():
    return {it["fact_id"]: it["options"] for it in json.loads((OUT / "options.json").read_text(encoding="utf-8"))}


def q_block(opts):
    return "\n".join(f"{f['fact_id']}. {f['question']}\n" + "\n".join(f"   {o['key']}. {o['text']}" for o in opts[f["fact_id"]])
                     for f in FACTS)


def score_choices(answers, opts):
    rows = []
    for a in answers:
        if a["fact_id"] not in opts:
            continue
        o = next(o for o in opts[a["fact_id"]] if o["key"] == a["choice"])
        rows.append({"fact_id": a["fact_id"], "choice": a["choice"], "score": 1.0 if o["correct"] else 0.0,
                     "critical": o["critical"], "dont_know": o["text"] == DONT_KNOW})
    return rows


def stage_answer():
    opts = options()
    people = {p["person_id"]: p for p in bm.people()}
    for rep in REPS:
        reads = jload(ROOT / rep / "reads.jsonl")

        def one(r):
            p = people[r["person_id"]]
            mem = "\n".join(f"- {m}" for m in r["memory"]) or "(남은 것 없음)"
            d = bm.call_json(ANS_PROMPT.format(card=ch.card(p), memory=mem, questions=q_block(opts)),
                             f"mc_answer:{rep}:{p['person_id']}", ANS_SCHEMA, max_tokens=1500)
            return {"person_id": p["person_id"], "grades": score_choices(d["answers"], opts)}

        with ThreadPoolExecutor(4) as pool:
            jdump(OUT / f"answers_{rep}.jsonl", list(pool.map(one, reads)))
        print(rep, "완료", flush=True)


def stage_baseline():
    opts = options()
    card = "[당신은 이런 사람입니다]\n보험에 대해 따로 공부한 적이 없는 일반 소비자."

    def one(i):
        d = bm.call_json(ANS_PROMPT.format(card=card, memory="(설명서를 읽지 않아 남은 것이 없습니다)",
                                           questions=q_block(opts)), f"mc_baseline:{i}", ANS_SCHEMA, max_tokens=1500)
        return {"n": i, "grades": score_choices(d["answers"], opts)}

    with ThreadPoolExecutor(4) as pool:
        jdump(OUT / "baseline.jsonl", list(pool.map(one, range(10))))


# ---------- 비교 ----------
def score(gs):
    return 100 * sum(g["score"] * FMAP[g["fact_id"]]["importance"] for g in gs if g["fact_id"] in FMAP) / TOT_W


def stage_compare():
    people = {p["person_id"]: p for p in bm.people()}
    fmt = {}
    for name, files in [("서술형", [ROOT / r / "grades.jsonl" for r in REPS]),
                        ("객관식", [OUT / f"answers_{r}.jsonl" for r in REPS])]:
        fmt[name] = [{g["person_id"]: g["grades"] for g in jload(f)} for f in files]
    S = {k: [{p: score(gs) for p, gs in run.items()} for run in v] for k, v in fmt.items()}
    ids = sorted(S["서술형"][0])
    mean = {k: {p: st.mean(r[p] for r in S[k]) for p in ids} for k in fmt}
    base_free = [score(b["grades"]) for b in jload(ROOT / "results_b" / "baseline.jsonl")]
    base_mc = [score(b["grades"]) for b in jload(OUT / "baseline.jsonl")]
    noise = {k: st.mean(st.pstdev([r[p] for r in S[k]]) for p in ids) for k in fmt}
    retest = {k: st.mean([st.correlation([S[k][a][p] for p in ids], [S[k][b][p] for p in ids])
                          for a, b in ((0, 1), (0, 2), (1, 2))]) for k in fmt}
    crit = {k: sum(g.get("critical", False) for run in fmt[k] for gs in run.values() for g in gs) / 3 for k in fmt}
    dk = sum(g.get("dont_know", False) for run in fmt["객관식"] for gs in run.values() for g in gs) / 3

    L = ["# 객관식 vs 서술형 비교 (같은 메모 3회분, 72명)", "", "> 같은 사람의 같은 메모로 답하는 형식만 바꿨다.", "",
         "| 항목 | 서술형 | 객관식 |", "|---|---|---|",
         f"| 전체 평균 (3회 평균) | {st.mean(mean['서술형'].values()):.1f} | {st.mean(mean['객관식'].values()):.1f} |",
         f"| 기준값 (읽지 않음) | {st.mean(base_free):.1f} | {st.mean(base_mc):.1f} |",
         f"| 같은 사람 점수 흔들림 (표준편차) | {noise['서술형']:.1f} | {noise['객관식']:.1f} |",
         f"| 회차 간 같은 사람 점수 상관 | {retest['서술형']:.2f} | {retest['객관식']:.2f} |",
         f"| 치명적 오해 (회당 평균 건수) | {crit['서술형']:.1f} | {crit['객관식']:.1f} |",
         f"| '모르겠다' 선택 (회당) | — | {dk:.1f} |",
         f"| 두 형식의 같은 사람 점수 상관 | {st.correlation([mean['서술형'][p] for p in ids], [mean['객관식'][p] for p in ids]):.2f} | |", "",
         "## 집단 차이 (3회 평균, 괄호는 회차별)", "", "| 집단 | 서술형 | 객관식 |", "|---|---|---|"]
    for key, vals in [("path", ["agent_talk", "guide_only", "clause_only", "full_terms"]), ("knowledge", ["상", "중", "하"]),
                      ("disposition", ["optimistic", "cautious"]), ("age_group", ["20대", "40대", "60대"])]:
        for v in vals:
            sel = [p for p in ids if people[p][key] == v]
            cells = []
            for k in ("서술형", "객관식"):
                per = [st.mean(r[p] for p in sel) for r in S[k]]
                cells.append(f"{st.mean(per):.1f} ({' / '.join(f'{x:.0f}' for x in per)})")
            L.append(f"| {key}={v} | {cells[0]} | {cells[1]} |")
    L += ["", "## 문항별 정답률 (3회 평균)", "", "| 문항 | 서술형 만점 비율 | 객관식 정답률 | 객관식 기준값 |", "|---|---|---|---|"]
    base = jload(OUT / "baseline.jsonl")
    for f in FACTS:
        fid = f["fact_id"]
        fr = st.mean(g["score"] == 1 for run in fmt["서술형"] for gs in run.values() for g in gs if g["fact_id"] == fid)
        mc = st.mean(g["score"] == 1 for run in fmt["객관식"] for gs in run.values() for g in gs if g["fact_id"] == fid)
        bs = st.mean(g["score"] == 1 for b in base for g in b["grades"] if g["fact_id"] == fid)
        L.append(f"| {fid} {f['category']} | {fr:.0%} | {mc:.0%} | {bs:.0%} |")
    (OUT / "compare.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


STAGES = {"options": stage_options, "answer": stage_answer, "baseline": stage_baseline, "compare": stage_compare}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=list(STAGES) + ["all"])
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    for s in (STAGES if a.stage == "all" else [a.stage]):
        print("==", s, flush=True)
        STAGES[s]()
