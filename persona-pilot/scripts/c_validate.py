"""다른 문서로 검증 (2026-11-28): c_tune 에서 확정한 설정(v5)을 '다시 조정하지 않고' 다른 상품 문서에 그대로 적용한다.

케이스 폴더 (예: results_valid/won/) 에 미리 둔다:
  document.txt : 페르소나가 읽을 상품요약서 발췌
  facts.json   : 질문 [{fact_id, question, answer, category, importance, units: [정답 근거 문구 정규식]}]
단계:
  terms    : 설명서에서 어려운 용어 뽑기 (AI, 한 번 만들고 고정) → terms.json
  options  : 보기 만들기 + 찍기 검사 (c_tune 과 같은 지시문·같은 검사) → options.json, guess.json
  run      : 확정 설정 v5 로 72명 실행 → <label>/summary.md
실행: python scripts/c_validate.py all --case won
"""

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


t = load("c_tune", "c_tune.py")
ch, bm = t.ch, t.bm

TERMS_SCHEMA = {"type": "object", "properties": {"terms": {"type": "array", "items": {"type": "string"}}},
                "required": ["terms"], "additionalProperties": False}
# Spring resources/prompts/guide_hard_terms_v1.md 와 같은 지시
TERMS_PROMPT = """아래 보험 상품설명서에서 보험을 잘 모르는 일반 소비자가 뜻을 정확히 모를 만한 보험 전문 용어를 최대 20개 고르세요 (terms).
- 설명서에 적힌 글자 그대로 쓰세요.
- 보험료, 치료, 진단처럼 일상에서 흔히 쓰는 말은 빼세요.

[상품설명서]
{doc}"""


def setup(case):
    d = ROOT / "results_valid" / case
    doc = (d / "document.txt").read_text(encoding="utf-8")
    facts = json.loads((d / "facts.json").read_text(encoding="utf-8"))
    t.FACTS = facts
    t.OUT = d
    t.OPT_FILE = d / "options.json"
    t.OPTS = t.load_opts() if t.OPT_FILE.exists() else {}
    t.DOC_OVERRIDE = doc
    bm.document = lambda: doc
    # 내용 단위 = 질문별 정답 근거 문구 (원래 파일럿의 CONTENT_UNITS 와 같은 방식, 문서마다 새로 정함)
    ch.CONTENT_UNITS = {f["fact_id"]: "|".join(f["units"]) for f in facts}
    tf = d / "terms.json"
    if tf.exists():
        ch.HARD_TERMS = json.loads(tf.read_text(encoding="utf-8"))
    gf = d / "guess.json"
    if gf.exists():
        guess = json.loads(gf.read_text(encoding="utf-8"))
        t.COMMON_SENSE = {k for k, v in guess.items() if v > 0.6}
    return d, doc


def stage_terms(d, doc):
    r = bm.call_json(TERMS_PROMPT.format(doc=doc), "valid_terms", TERMS_SCHEMA, max_tokens=2000)
    terms = [x for x in dict.fromkeys(r["terms"]) if x.strip() and x in doc]
    (d / "terms.json").write_text(json.dumps(terms, ensure_ascii=False, indent=1), encoding="utf-8")
    ch.HARD_TERMS = terms
    print("어려운 용어", len(terms), terms)


def stage_options(d, rounds=3, limit=0.4):
    t.stage_options()
    for r in range(rounds):
        rates = t.guess_rates(18)
        print(f"[{r + 1}회차] 찍기:", {k: f"{v:.0%}" for k, v in rates.items()}, flush=True)
        bad = [k for k, v in rates.items() if v > limit]
        if not bad or r == rounds - 1:
            break
        fb = "\n[이전 보기에서 읽지 않은 사람이 보기 문장만 보고 정답을 알아챈 문항]\n" + "\n".join(
            f"- {k}: 보기 순서를 섞어도 {rates[k]:.0%}가 정답을 고름. 이전 보기: "
            + " / ".join(o["text"] + ("(정답)" if o["correct"] else "") for o in t.OPTS[k]) for k in bad) + \
            "\n세 보기를 완전히 새로 쓰세요. 정답만 상식에 맞는 보기가 되지 않게 하세요.\n"
        t.stage_options(only=bad, feedback=fb)
    final = t.guess_rates(30)
    (d / "guess.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    t.COMMON_SENSE = {k for k, v in final.items() if v > 0.6}
    print("최종 찍기:", {k: f"{v:.0%}" for k, v in final.items()}, "상식 문항:", sorted(t.COMMON_SENSE))
    for f in t.FACTS:
        print(f["fact_id"], " | ".join(f"{o['key']}{'*' if o['correct'] else ''}{'!' if o['critical'] else ''} {o['text']}"
                                       for o in t.OPTS[f["fact_id"]]))


def stage_run(label):
    # 동양생명 문서로 정한 설정(results_tune/<label>/params.json)을 그대로 쓴다
    params = json.loads((ROOT / "results_tune" / label / "params.json").read_text(encoding="utf-8"))
    t.stage_run(label, params)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["terms", "options", "run", "all"])
    ap.add_argument("--case", default="won")
    ap.add_argument("--label", default="v5")
    a = ap.parse_args()
    d, doc = setup(a.case)
    if a.stage in ("terms", "all"):
        stage_terms(d, doc)
    if a.stage in ("options", "all"):
        stage_options(d)
    if a.stage in ("run", "all"):
        stage_run(a.label)
