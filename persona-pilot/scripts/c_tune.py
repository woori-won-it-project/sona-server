"""정답률 맞추기 (2026-11-28): '모르겠다' 없는 3지선다로, 정보를 덜어 내는 강도를 바꿔 가며 용어 이해 단계별 정답률을 잰다.

목표 (사용자 결정): 용어 이해 하 40%대 / 중 60%대 / 상 80%대.
원칙: 잘못된 믿음을 넣지 않는다. 덜어 내는 정도(문장 자르기, 용어 가리기, 메모 글자 수, 내용 놓치기, 읽기 확률)만 바꾼다.
정보 경로는 '설명서 직접 읽음'(guide_only)으로 고정한다 (서비스에서 페르소나는 상품설명서만 읽는다).

  run      : 72명 읽기(C안 v4 규칙, 아래 설정값) → 메모만 보고 3지선다 강제 선택 → 코드 채점
  baseline : 읽지 않고 3지선다 강제 선택 10회 (찍기 수준 확인)
실행: python scripts/c_tune.py run --label v0 [--set '{"memo_max": 600}']
     python scripts/c_tune.py baseline
결과: results_tune/<label>/  (reads.jsonl, answers.jsonl, summary.md, params.json)
"""

import argparse
import importlib.util
import json
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results_tune"
DOC_OVERRIDE = None  # 다른 문서로 검증할 때 c_validate.py 가 채운다


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ch = load("c_hybrid", "c_hybrid.py")
bm, bp = ch.bm, ch.bp
ORIG_CARD = ch.card
FACTS = json.loads((ROOT / "results_b" / "facts.json").read_text(encoding="utf-8"))
# 보기: results_tune/options.json (찍기 검사를 통과한 보기)이 있으면 그것을, 없으면 c_mc 보기에서 '모르겠다'(D)를 뺀 것
OPT_FILE = ROOT / "results_tune" / "options.json"


def load_opts():
    if OPT_FILE.exists():
        return {it["fact_id"]: it["options"] for it in json.loads(OPT_FILE.read_text(encoding="utf-8"))}
    return {it["fact_id"]: [o for o in it["options"] if o["key"] != "D"]
            for it in json.loads((ROOT / "results_mc" / "options.json").read_text(encoding="utf-8"))}


OPTS = load_opts()
# 읽지 않고도 맞히는 상식 문항 (찍기 검사 60% 초과). 정답률 집계에서 뺀다 (F6 갱신 보험료 인상: 찍기 100%)
COMMON_SENSE = {"F6"}

# 현재 값 (C안 v4). --set 으로 바꾼다
DEFAULTS = {
    "sent_chars": {"하": 40, "중": 70, "상": None},   # 한 문장에서 읽는 글자 수
    "mask": {"하": 1.0, "중": 0.5, "상": 0.0},         # 어려운 용어를 □□로 가릴 확률
    "memo_min": 150, "memo_max": 400,                  # 메모 글자 수 (꼼꼼함 0.30 ~ 0.75)
    "unit_base": 0.2,                                  # 핵심 내용을 볼 확률 = unit_base + 꼼꼼함 (+ unit_bonus)
    "unit_bonus": {"하": 0.0, "중": 0.0, "상": 0.0},
    "budget_base": 0.55, "budget_slope": 0.25,         # 문장 읽힘 확률 기본값
}

ANS_SCHEMA = {"type": "object", "properties": {"answers": {"type": "array", "items": {
    "type": "object", "properties": {"fact_id": {"type": "string"}, "choice": {"type": "string", "enum": list("ABC")}},
    "required": ["fact_id", "choice"], "additionalProperties": False}}},
    "required": ["answers"], "additionalProperties": False}

# Spring resources/prompts/persona_answer_v1.md 와 같은 지시
ANS_PROMPT = """{card}

조금 전 보험 상품설명서를 읽었고, 지금은 설명서를 다시 볼 수 없습니다.
설명서를 읽고 머릿속에 남은 것은 아래가 전부입니다.

[머릿속에 남은 것]
{memory}

창구 직원이 아래 질문을 하며 보기를 보여 줍니다. 머릿속에 남은 것을 떠올리며 이 사람이 고를 보기를 질문마다 하나씩 고르세요.
- 반드시 A, B, C 중 하나를 고르세요. 확실하지 않아도 이 사람이 가장 그럴듯하다고 생각할 보기를 고릅니다.
- 남은 것에 없는 내용은 이 사람이 떠올릴 법한 생각대로 고르세요.

[질문과 보기]
{questions}"""


def q_block():
    return "\n".join(f"{f['fact_id']}. {f['question']}\n" + "\n".join(f"   {o['key']}. {o['text']}" for o in OPTS[f["fact_id"]])
                     for f in FACTS)


def apply(params):
    """c_hybrid 의 설정값을 바꾼다 (프로세스 안에서만)."""
    ch.SENTENCE_CHARS.clear()
    ch.SENTENCE_CHARS.update(params["sent_chars"])
    ch.MASK_RATE.clear()
    ch.MASK_RATE.update(params["mask"])
    ch.MEMO_CHARS_MIN, ch.MEMO_CHARS_MAX = params["memo_min"], params["memo_max"]
    bp.RULES["budget_base"], bp.RULES["budget_slope"] = params["budget_base"], params["budget_slope"]
    bonus = params["unit_bonus"]
    # 메모 정리 습관 (용어 이해 단계별, 2026-11-28 v5): 읽기 지시문에만 붙인다. 잘못된 내용을 넣지 않고 '무엇을 얼마나 적는지'만 다르게
    style = params.get("memo_style") or {}
    if style:
        ch.card = lambda p, _c=ORIG_CARD: _c(p) + ("\n메모 습관: " + style[p["knowledge"]] if p["knowledge"] in style else "")
    else:
        ch.card = ORIG_CARD

    def hide_units(p, sentences):
        import re
        p_catch = min(1.0, params["unit_base"] + float(p["diligence"]) + bonus.get(p["knowledge"], 0.0))
        missed = []
        for i, (unit, rx) in enumerate(ch.CONTENT_UNITS.items()):
            if bp.sentence_rng(int(p["seed"]), "C_UNIT:" + unit, i).random() < p_catch:
                continue
            missed.append(unit)
            for s in sentences:
                if s["read"] and re.search(rx, s["text"]):
                    s["read"], s["hidden_unit"] = False, unit
        return missed

    ch.hide_content_units = hide_units


def grade(answers):
    rows = []
    for a in answers:
        opts = OPTS.get(a["fact_id"])
        if not opts:
            continue
        o = next((o for o in opts if o["key"] == a["choice"]), None)
        rows.append({"fact_id": a["fact_id"], "choice": a["choice"], "correct": bool(o and o["correct"]),
                     "critical": bool(o and o["critical"])})
    return rows


def stage_run(label, params):
    apply(params)
    out = OUT / label
    out.mkdir(parents=True, exist_ok=True)
    (out / "params.json").write_text(json.dumps(params, ensure_ascii=False, indent=1), encoding="utf-8")
    docs = ({"guide_only": {"text": DOC_OVERRIDE}} if DOC_OVERRIDE
            else json.loads((ROOT / "results_c" / "path_docs.json").read_text(encoding="utf-8")))
    people = [{**p, "path": "guide_only"} for p in bm.people()]
    qs = q_block()

    scale = params.get("memo_scale") or {}
    ratio = params.get("memo_ratio") or {}

    def read_one(p):
        # c_hybrid.read_one 과 같고, 메모 한도에 용어 이해 단계별 배수(memo_scale)만 곱한다
        sentences = bp.read_text(p, "C_DOC", docs[p["path"]]["text"])
        missed_units = ch.hide_content_units(p, sentences)
        cut = ch.truncate_long(p, sentences)
        seen, masked = ch.mask_terms(p, "\n".join(s["text"] for s in sentences if s["read"]))
        if ratio:
            # v6: 메모 한도 = 문서 길이 x 이해 단계 비율 x 꼼꼼함 계수(0.6 ~ 1.4). 문서가 짧으면 메모도 짧아진다
            dl = min(1.0, max(0.0, (float(p["diligence"]) - 0.30) / 0.45))
            budget = round(len(docs[p["path"]]["text"]) * ratio[p["knowledge"]] * (0.6 + 0.8 * dl))
        else:
            budget = round(ch.memo_budget(float(p["diligence"])) * scale.get(p["knowledge"], 1.0))
        d = bm.call_json(ch.READ_PROMPT_V3.format(card=ch.card(p), path_name=ch.PATH_NAME[p["path"]], budget=budget, seen=seen),
                         f"tune_read:{p['person_id']}", bm.READ_SCHEMA, max_tokens=4000)
        d["memory"] = ch.cut_memo(d["memory"], budget)
        return {"person_id": p["person_id"], "read_count": sum(s["read"] for s in sentences), "total": len(sentences),
                "missed_units": missed_units, "sentences_cut": cut, "masked_terms": masked, "memo_budget": budget, **d}

    def one(p):
        r = read_one(p)
        mem = "\n".join(f"- {m}" for m in r["memory"]) or "(남은 것 없음)"
        d = bm.call_json(ANS_PROMPT.format(card=ORIG_CARD(p), memory=mem, questions=qs),
                         f"tune_answer:{label}:{p['person_id']}", ANS_SCHEMA, max_tokens=1500)
        read = {k: r[k] for k in ("person_id", "read_count", "total", "missed_units", "sentences_cut", "masked_terms",
                                  "memo_budget", "memory")}
        return read, {"person_id": p["person_id"], "grades": grade(d["answers"])}

    with ThreadPoolExecutor(6) as pool:
        res = list(pool.map(one, people))
    (out / "reads.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r, _ in res) + "\n", encoding="utf-8")
    (out / "answers.jsonl").write_text("\n".join(json.dumps(a, ensure_ascii=False) for _, a in res) + "\n", encoding="utf-8")
    summarize(label)


def acc(gs):
    return 100 * sum(g["correct"] for g in gs) / max(1, len(gs))


def summarize(label):
    out = OUT / label
    people = {p["person_id"]: p for p in bm.people()}
    answers = [json.loads(l) for l in (out / "answers.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    reads = {json.loads(l)["person_id"]: json.loads(l) for l in (out / "reads.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    score = {a["person_id"]: acc([g for g in a["grades"] if g["fact_id"] not in COMMON_SENSE]) for a in answers}
    L = [f"# 정답률 맞추기 {label}", "", "설정: `" + (out / "params.json").read_text(encoding="utf-8").replace("\n", "") + "`", "",
         f"전체 정답률 {st.mean(score.values()):.1f}% (72명, 상식 문항 {sorted(COMMON_SENSE)} 제외, 3지선다, 찍기 약 30%)", "",
         "| 집단 | 정답률 | 읽은 문장 | 놓친 내용 | 메모 글자 |", "|---|---|---|---|---|"]
    for key, vals in [("knowledge", ["상", "중", "하"]), ("age_group", ["20대", "40대", "60대"]),
                      ("disposition", ["optimistic", "cautious"])]:
        for v in vals:
            ids = [p for p in score if people[p][key] == v]
            rd = [reads[p] for p in ids]
            L.append(f"| {key}={v} ({len(ids)}명) | {st.mean(score[p] for p in ids):.1f}% "
                     f"| {st.mean(r['read_count'] / r['total'] for r in rd):.0%} "
                     f"| {st.mean(len(r['missed_units']) for r in rd):.1f}개 "
                     f"| {st.mean(sum(len(m) for m in r['memory']) for r in rd):.0f}자 |")
    L += ["", "| 문항 | 정답률 | 상 | 중 | 하 | 치명적 오해 |", "|---|---|---|---|---|---|"]
    for f in FACTS:
        fid = f["fact_id"]

        def rate(level=None):
            gs = [g for a in answers for g in a["grades"] if g["fact_id"] == fid
                  and (level is None or people[a["person_id"]]["knowledge"] == level)]
            return st.mean(g["correct"] for g in gs) if gs else 0

        crit = sum(g["critical"] for a in answers for g in a["grades"] if g["fact_id"] == fid)
        L.append(f"| {fid} {f['category']} | {rate():.0%} | {rate('상'):.0%} | {rate('중'):.0%} | {rate('하'):.0%} | {crit} |")
    (out / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def stage_baseline():
    card = "[당신은 이런 사람입니다]\n보험에 대해 따로 공부한 적이 없는 일반 소비자."
    qs = q_block()

    def one(i):
        d = bm.call_json(ANS_PROMPT.format(card=card, memory="(설명서를 읽지 않아 남은 것이 없습니다)", questions=qs),
                         f"tune_baseline:{i}", ANS_SCHEMA, max_tokens=1500)
        return grade(d["answers"])

    with ThreadPoolExecutor(5) as pool:
        runs = list(pool.map(one, range(10)))
    out = OUT / "baseline"
    out.mkdir(parents=True, exist_ok=True)
    (out / "baseline.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in runs) + "\n", encoding="utf-8")
    L = ["# 읽지 않고 고르기 (10회)", "", f"전체 정답률 {st.mean(acc(r) for r in runs):.1f}%", ""]
    for f in FACTS:
        L.append(f"- {f['fact_id']}: {st.mean(g['correct'] for r in runs for g in r if g['fact_id'] == f['fact_id']):.0%}")
    (out / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


# ---------- 보기 다시 만들기 + 찍기 검사 ----------
OPT_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {
        "fact_id": {"type": "string"}, "correct": {"type": "string"},
        "wrong": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "critical": {"type": "boolean"}},
            "required": ["text", "critical"], "additionalProperties": False}}},
    "required": ["fact_id", "correct", "wrong"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}

OPT_PROMPT_V2 = """아래 보험 상품설명서와 문항마다 3지선다 보기를 만드세요. 이 보기는 '설명서를 읽고 기억하는지'를 재는 데 씁니다.
그래서 설명서를 읽지 않은 사람이 상식이나 눈치로 정답을 고를 수 없어야 합니다.

- correct: 문서 기준 정답 1개. wrong: 그럴듯한 오답 정확히 2개.
- 세 보기 모두 20~35자, 같은 문장 구조, 같은 말투로 쓰세요.
- 정답이 '가장 신중해 보이는 보기', '가장 무난한 보기', '조건이 붙은 보기'가 되면 안 됩니다.
  정답에 "~될 수 있음", "~만", "~제외" 같은 표현이 있으면 오답에도 같은 종류의 표현을 넣으세요.
- 오답에 "무조건", "전액", "자동으로", "연 10%씩"처럼 상식으로 바로 틀렸다고 보이는 말을 쓰지 마세요.
  오답은 설명서에 나오는 다른 숫자·기간·조건을 섞어, 읽지 않은 사람에게는 정답과 똑같이 그럴듯해야 합니다.
- critical = 실제보다 더 많이 받거나 없는 보장·권리를 있다고 믿는 오답이면 true.
{feedback}
[문항과 기준 답]
{facts}

[상품설명서]
{doc}"""


def stage_options(only=None, feedback=""):
    facts = [f for f in FACTS if not only or f["fact_id"] in only]
    block = "\n".join(f"{f['fact_id']}. {f['question']}\n   기준 답: {f['answer']}" for f in facts)
    d = bm.call_json(OPT_PROMPT_V2.format(facts=block, doc=bm.document(), feedback=feedback),
                     "tune_options", OPT_SCHEMA, **bm.STRONG)
    cur = load_opts() if OPT_FILE.exists() else {}
    import random
    for it in d["items"]:
        if it["fact_id"] not in {f["fact_id"] for f in facts}:
            continue
        opts = [{"text": it["correct"], "correct": True, "critical": False}] + \
               [{"text": w["text"], "correct": False, "critical": w["critical"]} for w in it["wrong"][:2]]
        random.Random(it["fact_id"]).shuffle(opts)
        for k, o in zip("ABC", opts):
            o["key"] = k
        cur[it["fact_id"]] = opts
    OPT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OPT_FILE.write_text(json.dumps([{"fact_id": k, "options": v} for k, v in sorted(cur.items())],
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    global OPTS
    OPTS = cur


def guess_rates(n=12):
    """읽지 않고 고를 때 문항별 정답률.
    같은 글이면 AI 가 늘 같은 보기를 골라 0%/100% 로 튀므로, 회차마다 보기 순서를 섞고 사람 카드도 바꿔
    '보기 문장만 보고 정답을 알아챌 수 있는지'를 잰다. 단서가 없으면 33% 근처가 나온다."""
    import random
    people = bm.people()

    def one(i):
        rng = random.Random(1000 + i)
        perm = {}
        lines = []
        for f in FACTS:
            opts = OPTS[f["fact_id"]][:]
            rng.shuffle(opts)
            perm[f["fact_id"]] = {k: o for k, o in zip("ABC", opts)}
            lines.append(f"{f['fact_id']}. {f['question']}\n" + "\n".join(f"   {k}. {o['text']}" for k, o in perm[f["fact_id"]].items()))
        p = people[(i * 7) % len(people)]
        d = bm.call_json(ANS_PROMPT.format(card=ch.card(p), memory="(설명서를 읽지 않아 남은 것이 없습니다)",
                                           questions="\n".join(lines)), f"tune_guess:{i}", ANS_SCHEMA, max_tokens=1500)
        return [{"fact_id": a["fact_id"], "correct": bool(perm.get(a["fact_id"], {}).get(a["choice"], {}).get("correct"))}
                for a in d["answers"] if a["fact_id"] in perm]

    with ThreadPoolExecutor(6) as pool:
        runs = list(pool.map(one, range(n)))
    return {f["fact_id"]: st.mean(g["correct"] for r in runs for g in r if g["fact_id"] == f["fact_id"]) for f in FACTS}


def stage_rebuild(limit=0.4, rounds=4):
    """보기를 새로 만들고, 읽지 않고 맞히는 비율이 limit 를 넘는 문항만 다시 만든다."""
    stage_options()
    log = []
    for r in range(rounds):
        rates = guess_rates()
        log.append({"round": r + 1, "rates": rates})
        print(f"[{r + 1}회차] 찍기 정답률:", {k: f"{v:.0%}" for k, v in rates.items()}, flush=True)
        bad = [k for k, v in rates.items() if v > limit]
        if not bad:
            break
        fb = "\n[이전 보기에서 읽지 않은 사람이 정답을 너무 쉽게 골랐던 문항]\n" + "\n".join(
            f"- {k}: 읽지 않고도 {rates[k]:.0%}가 정답을 고름. 이전 보기: "
            + " / ".join(f"{o['text']}{'(정답)' if o['correct'] else ''}" for o in OPTS[k]) for k in bad) + \
            "\n정답이 티 나지 않도록 세 보기를 완전히 새로 쓰세요.\n"
        if r < rounds - 1:
            stage_options(only=bad, feedback=fb)
    (OUT / "options_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in FACTS:
        print(f["fact_id"], " | ".join(f"{o['key']}{'*' if o['correct'] else ''}{'!' if o['critical'] else ''} {o['text']}"
                                       for o in OPTS[f["fact_id"]]))


def merge(base, over):
    out = json.loads(json.dumps(base))
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["run", "baseline", "summary", "rebuild"])
    ap.add_argument("--label", default="v0")
    ap.add_argument("--set", default="{}", help="DEFAULTS 위에 덮어쓸 JSON")
    a = ap.parse_args()
    if a.stage == "run":
        stage_run(a.label, merge(DEFAULTS, json.loads(a.set)))
    elif a.stage == "baseline":
        stage_baseline()
    elif a.stage == "rebuild":
        stage_rebuild()
    else:
        summarize(a.label)
