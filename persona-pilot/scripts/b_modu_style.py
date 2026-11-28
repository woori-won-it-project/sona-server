"""B안: '모의창구' 방식 재현 테스트. (A안 01~07 과 별개, A안 파일은 건드리지 않음)

흐름 (모의창구 공개 화면에서 확인한 동작을 따름)
  1. questions : 문서에서 핵심 사실 6개와 창구 질문·문서 기준 답·근거·중요도를 만든다
  2. read      : 가상고객이 문서를 읽고, 문서를 덮은 뒤 '머릿속에 남은 것'을 자기 말로 K개 적는다
                 (K = 모든 사람 7개 고정. 금융 친숙도별 차등은 2026-11-27 뺌)
  3. answer    : 문서 없이 자기 메모만 보고 창구 질문에 말로 답한다 (+ 가입 판단)
  4. grade     : 채점관이 문서 기준 답과 비교해 1 / 0.5 / 0 점, 치명적 오해 여부, 근거 한 줄
  5. baseline  : 문서를 읽지 않은 상태(메모 없음)로 같은 질문에 답하고 채점 → AI 상식만으로 맞히는 정도
  6. report    : results_b/report_b.md

실행 (persona-pilot 폴더에서):  python scripts/b_modu_style.py all
                               python scripts/b_modu_style.py <stage>   (한 단계만)
'모름'은 0점(이해 못 함)으로 센다. 결과는 가상고객 시뮬레이션이며 실제 소비자 조사가 아니다.
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_llm import SETTINGS, call_with_retry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results_b"
WORKERS = 4

# 기억 줄 수: 모든 사람 같은 값 (2026-11-27 사용자 결정, '기억 줄 수' 규칙은 넣지 않음)
#   이전: 지식 하 5 / 중 7 / 상 9 (모의창구 화면 값 참고, 근거 없음)
#   이유: 근거 없는 규칙이고, 차이는 이미 꼼꼼함(못 본 문장)·용어 이해 단계가 만든다 (같은 원인을 두 번 세지 않음)
MEMORY_ITEMS = 7
FAMILIARITY = {"하": "낮음", "중": "보통", "상": "높음"}
DISPOSITION = {
    "optimistic": "애매한 부분이 있으면 보장되는 쪽으로 받아들이는 편입니다.",
    "cautious": "애매한 부분이 있으면 보장되지 않을 수도 있다고 생각하는 편입니다.",
}
# 문항 생성·채점은 정확도가 중요해 생각 기능을 켠다. 가상고객 읽기·답변은 settings.yaml 값(생각 끔)
STRONG = {"thinking": "adaptive", "effort": "high", "max_tokens": 16000}
BASELINE_N = 10


def jdump(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def jload(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def call_json(prompt: str, purpose: str, schema: dict, **kw) -> dict:
    r = None
    for _ in range(3):
        r = call_with_retry(prompt, purpose, json_schema=schema, **kw)
        if r["stop_reason"] == "end_turn":
            try:
                return json.loads(r["text"])
            except json.JSONDecodeError:
                pass
    raise RuntimeError(f"{purpose}: JSON 응답을 받지 못함 (stop_reason={r['stop_reason'] if r else None})")


# ---------- 0. 문서 ----------
def build_document() -> str:
    """상품설명서 2~4쪽 (1쪽은 연락처·홍보). 2단 편집이라 왼쪽 단 → 오른쪽 단 순서로 블록을 잇는다."""
    parts = []
    with pymupdf.open(ROOT / "data" / "raw" / "guide.pdf") as doc:
        for pno in (1, 2, 3):
            page = doc[pno]
            mid = page.rect.width / 2
            blocks = [b for b in page.get_text("blocks") if b[4].strip()]
            blocks.sort(key=lambda b: (0 if b[0] < mid - 10 else 1, round(b[1]), b[0]))
            parts.append("\n".join(re.sub(r"\s+", " ", b[4].replace("\x07", "")).strip() for b in blocks))
    text = "\n\n".join(parts)
    (OUT / "document.txt").write_text(text, encoding="utf-8")
    return text


def document() -> str:
    p = OUT / "document.txt"
    return p.read_text(encoding="utf-8") if p.exists() else build_document()


# ---------- 1. 핵심 사실·문항 ----------
FACT_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "fact": {"type": "string"}, "question": {"type": "string"}, "answer": {"type": "string"},
            "evidence": {"type": "string"}, "importance": {"type": "integer", "enum": [1, 2, 3]},
            "category": {"type": "string", "enum": ["보장", "지급제한·감액", "해지·환급", "갱신·보험료", "기타"]},
        },
        "required": ["fact", "question", "answer", "evidence", "importance", "category"],
        "additionalProperties": False,
    }}},
    "required": ["facts"], "additionalProperties": False,
}

FACT_PROMPT = """다음은 보험 상품설명서입니다. 소비자가 가입 전에 꼭 이해해야 할 핵심 사실 6개를 뽑고,
사실마다 창구 직원이 소비자의 이해를 확인하는 질문 1개를 만드세요.

규칙
- 보장, 지급 제한·감액, 해지·환급, 갱신·보험료를 고르게 다루세요.
- 일반 상식으로는 맞힐 수 없고 이 문서를 읽어야 알 수 있는 구체적인 조건·숫자·기간을 우선하세요.
- 질문은 소비자가 이해하는 말로, 구체적인 상황을 들어 묻되 답을 암시하는 표현은 쓰지 마세요.
  (예/아니요만 고르게 하지 말고 '얼마', '몇 %', '언제부터', '어떻게 되나요'처럼 열린 질문을 섞으세요.)
- answer 는 문서 기준 정답을 한 문장으로, evidence 는 근거가 되는 문서 문장을 그대로 옮기세요.
- importance 는 오해했을 때 금전 손실이 큰 정도 (3 = 큼).

[문서]
{doc}"""


def stage_questions() -> list[dict]:
    d = call_json(FACT_PROMPT.format(doc=document()), "b_questions", FACT_SCHEMA, **STRONG)
    facts = [{"fact_id": f"F{i}", **f} for i, f in enumerate(d["facts"], 1)]
    (OUT / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in facts:
        print(f"{f['fact_id']} [{f['category']}·중요도 {f['importance']}] {f['question']}\n   → {f['answer']}")
    return facts


# ---------- 가상고객 ----------
def people() -> list[dict]:
    with (ROOT / "data" / "personas.csv").open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def persona_card(p: dict) -> str:
    return (f"[당신은 이런 사람입니다]\n{p['age']}세. {p['backstory']}\n"
            f"금융 친숙도: {FAMILIARITY[p['knowledge']]}\n성향: {DISPOSITION[p['disposition']]}")


# ---------- 2. 읽기 ----------
READ_SCHEMA = {
    "type": "object",
    "properties": {
        "first_impression": {"type": "string"},
        "memory": {"type": "array", "items": {"type": "string"}},
        "hard_parts": {"type": "array", "items": {
            "type": "object", "properties": {"quote": {"type": "string"}, "why": {"type": "string"}},
            "required": ["quote", "why"], "additionalProperties": False}},
    },
    "required": ["first_impression", "memory", "hard_parts"], "additionalProperties": False,
}

READ_PROMPT = """{card}

지금 은행 창구에서 아래 보험 상품설명서를 처음 받아 한 번 읽습니다. 이 사람이 실제로 읽는다고 생각하고 읽으세요.
읽은 뒤 설명서는 돌려주게 되어 다시 볼 수 없습니다.

설명서를 덮은 뒤 머릿속에 남은 것을 이 사람의 말투로 정확히 {k}개 적으세요.
- 모든 내용을 기억하는 사람은 없습니다. 이 사람에게 인상 깊었던 것, 이해한 만큼만 남습니다.
또 첫인상 한두 문장과, 이해하기 어려웠던 대목 2~3개(설명서 문구 그대로 + 어려웠던 이유)를 적으세요.

[보험 상품설명서]
{doc}"""


def read_one(p: dict) -> dict:
    k = MEMORY_ITEMS
    d = call_json(READ_PROMPT.format(card=persona_card(p), k=k, doc=document()), f"b_read:{p['person_id']}", READ_SCHEMA)
    return {"person_id": p["person_id"], "k": k, **d}


def stage_read() -> None:
    with ThreadPoolExecutor(WORKERS) as pool:
        rows = list(pool.map(read_one, people()))
    jdump(OUT / "reads.jsonl", rows)
    print(f"읽기 {len(rows)}명, 기억 개수 일치 {sum(len(r['memory']) == r['k'] for r in rows)}명")


# ---------- 3. 답하기 ----------
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {"type": "array", "items": {
            "type": "object",
            "properties": {"fact_id": {"type": "string"}, "answer": {"type": "string"},
                           "confidence": {"type": "integer", "enum": [1, 2, 3, 4, 5]}},
            "required": ["fact_id", "answer", "confidence"], "additionalProperties": False}},
        "join_decision": {"type": "string", "enum": ["가입하겠다", "모르겠다", "가입하지 않겠다"]},
        "join_reason": {"type": "string"},
    },
    "required": ["answers", "join_decision", "join_reason"], "additionalProperties": False,
}

ANSWER_PROMPT = """{card}

조금 전 보험 상품설명서를 읽었고, 지금은 설명서를 다시 볼 수 없습니다.
설명서를 읽고 머릿속에 남은 것은 아래가 전부입니다.

[머릿속에 남은 것]
{memory}

창구 직원이 아래 질문을 합니다. 머릿속에 남은 것을 떠올리며 이 사람의 말투로 1~2문장씩 답하세요.
남은 것에 없는 내용은 이 사람이 떠올릴 법한 생각대로 말하고, 전혀 모르겠으면 모르겠다고 말하세요.
질문마다 본인 확신(1~5)을 붙이고, 마지막으로 이 보험에 가입할지와 그 이유를 말하세요.

[질문]
{questions}"""


def answer_one(p: dict | None, memory: list[str], facts: list[dict], purpose: str) -> dict:
    mem = "\n".join(f"- {m}" for m in memory) if memory else "(설명서를 읽지 않아 남은 것이 없습니다)"
    card = persona_card(p) if p else "[당신은 이런 사람입니다]\n보험에 대해 따로 공부한 적이 없는 일반 소비자."
    qs = "\n".join(f"{f['fact_id']}. {f['question']}" for f in facts)
    return call_json(ANSWER_PROMPT.format(card=card, memory=mem, questions=qs), purpose, ANSWER_SCHEMA)


def stage_answer() -> None:
    facts = json.loads((OUT / "facts.json").read_text(encoding="utf-8"))
    reads = {r["person_id"]: r for r in jload(OUT / "reads.jsonl")}
    ps = people()
    with ThreadPoolExecutor(WORKERS) as pool:
        res = list(pool.map(
            lambda p: answer_one(p, reads[p["person_id"]]["memory"], facts, f"b_answer:{p['person_id']}"), ps))
    jdump(OUT / "answers.jsonl", [{"person_id": p["person_id"], **d} for p, d in zip(ps, res)])
    print(f"답변 {len(res)}명")


# ---------- 4. 채점 ----------
GRADE_SCHEMA = {
    "type": "object",
    "properties": {"grades": {"type": "array", "items": {
        "type": "object",
        "properties": {"fact_id": {"type": "string"}, "score": {"type": "number", "enum": [0, 0.5, 1]},
                       "critical": {"type": "boolean"}, "rationale": {"type": "string"}},
        "required": ["fact_id", "score", "critical", "rationale"], "additionalProperties": False}}},
    "required": ["grades"], "additionalProperties": False,
}

GRADE_PROMPT = """당신은 보험 설명서 이해도 조사의 채점관입니다. 소비자의 답을 문서 기준 답과 비교해 채점하세요.

점수: 1 = 기준 답의 핵심을 맞게 말함 / 0.5 = 일부만 맞거나 핵심 조건·숫자가 빠짐 / 0 = 틀림, 모른다고 함, 질문과 무관함
critical(치명적 오해): 문서에 없는 보장·수익·권리를 있다고 믿거나, 받을 수 있는 금액을 실제보다 크게 믿는 등
  금전 손실로 이어질 수 있게 반대로 이해한 경우에만 true. 모른다고 한 경우는 false.
rationale: 판정 이유 한 문장.

[문항과 기준]
{criteria}

[소비자의 답]
{answers}"""


def grade_one(answers: list[dict], facts: list[dict], purpose: str) -> list[dict]:
    criteria = "\n".join(
        f"{f['fact_id']}. 질문: {f['question']}\n   기준 답: {f['answer']}\n   근거: {f['evidence']}" for f in facts)
    ans = "\n".join(f"{a['fact_id']}. {a['answer']}" for a in answers)
    return call_json(GRADE_PROMPT.format(criteria=criteria, answers=ans), purpose, GRADE_SCHEMA, **STRONG)["grades"]


def stage_grade() -> None:
    facts = json.loads((OUT / "facts.json").read_text(encoding="utf-8"))
    answers = jload(OUT / "answers.jsonl")
    with ThreadPoolExecutor(WORKERS) as pool:
        res = list(pool.map(lambda a: grade_one(a["answers"], facts, f"b_grade:{a['person_id']}"), answers))
    jdump(OUT / "grades.jsonl", [{"person_id": a["person_id"], "grades": g} for a, g in zip(answers, res)])
    print(f"채점 {len(res)}명")


# ---------- 5. 기준값 ----------
def stage_baseline() -> None:
    facts = json.loads((OUT / "facts.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(WORKERS) as pool:
        ans = list(pool.map(lambda i: answer_one(None, [], facts, f"b_baseline_answer:{i}"), range(BASELINE_N)))
        grades = list(pool.map(lambda iv: grade_one(iv[1]["answers"], facts, f"b_baseline_grade:{iv[0]}"),
                               enumerate(ans)))
    jdump(OUT / "baseline.jsonl", [{"n": i, **a, "grades": g} for i, (a, g) in enumerate(zip(ans, grades))])
    print(f"기준값 {BASELINE_N}회")


# ---------- 6. 리포트 ----------
def pct(x: float) -> str:
    return f"{x:.0%}"


def stage_report() -> None:
    facts = json.loads((OUT / "facts.json").read_text(encoding="utf-8"))
    fmap = {f["fact_id"]: f for f in facts}
    ps = {p["person_id"]: p for p in people()}
    reads = {r["person_id"]: r for r in jload(OUT / "reads.jsonl")}
    answers = {a["person_id"]: a for a in jload(OUT / "answers.jsonl")}
    grades = {g["person_id"]: {x["fact_id"]: x for x in g["grades"]} for g in jload(OUT / "grades.jsonl")}
    base = jload(OUT / "baseline.jsonl") if (OUT / "baseline.jsonl").exists() else []

    rows = []
    for pid, g in grades.items():
        ans = {a["fact_id"]: a for a in answers[pid]["answers"]}
        for fid, x in g.items():
            if fid in fmap:
                rows.append({"pid": pid, "fid": fid, "score": x["score"], "critical": x["critical"],
                             "rationale": x["rationale"], "answer": ans.get(fid, {}).get("answer", ""),
                             **{k: ps[pid][k] for k in ("age_group", "knowledge", "disposition")}})

    def person_score(pid: str) -> float:  # 모의창구: 문항 점수 × 중요도의 가중 평균 (100점)
        g = grades[pid]
        w = sum(fmap[f]["importance"] for f in g if f in fmap)
        return 100 * sum(g[f]["score"] * fmap[f]["importance"] for f in g if f in fmap) / w

    def avg(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    L = ["# B안 결과: 모의창구 방식 재현 테스트", "",
         "> 가상고객 48명 LLM 시뮬레이션 결과입니다. 실제 소비자 조사가 아닙니다.",
         "> 흐름: 설명서 읽기 → 문서를 덮고 '머릿속에 남은 것' 적기 → 그 메모만 보고 창구 질문에 답하기 → 채점관 채점.",
         f"> 문서: 상품설명서 2~4쪽 ({len(document()):,}자). 기억 개수: 모두 {MEMORY_ITEMS}개. '모름'은 0점.", ""]

    L += ["## 1. 문항별 결과", "",
          "| 문항 | 분류 | 중요도 | 이해(1) | 일부(0.5) | 못 함(0) | 치명적 오해 | 기준값 만점 |",
          "|---|---|---|---|---|---|---|---|"]
    for f in facts:
        sel = [r for r in rows if r["fid"] == f["fact_id"]]
        c, n = Counter(r["score"] for r in sel), max(1, len(sel))
        b = [x for bb in base for x in bb["grades"] if x["fact_id"] == f["fact_id"]]
        base_full = f"{sum(x['score'] == 1 for x in b)}/{len(b)}" if b else "-"
        L.append(f"| {f['fact_id']} | {f['category']} | {f['importance']} | {pct(c[1] / n)} | {pct(c[0.5] / n)} | "
                 f"{pct(c[0] / n)} | {sum(r['critical'] for r in sel)}명 | {base_full} |")
    L += ["", "기준값 만점 = 설명서를 읽지 않고(메모 없이) 답했을 때 만점 받은 횟수. 높으면 AI 상식만으로 맞히는 문항입니다.", ""]
    for f in facts:
        L += [f"- **{f['fact_id']}** {f['question']}", f"  - 기준 답: {f['answer']}"]
    L.append("")

    L += ["## 2. 집단별 평균 이해도 (중요도 가중, 100점)", ""]
    for key, name, vals in [("age_group", "연령대", SETTINGS["age_groups"]),
                            ("knowledge", "지식(금융 친숙도)", ["상", "중", "하"]),
                            ("disposition", "성향", ["optimistic", "cautious"])]:
        L.append(f"- **{name}**: " + " · ".join(
            f"{v} {avg([person_score(p) for p in grades if ps[p][key] == v]):.1f}점" for v in vals))
    L.append(f"- **전체 평균**: {avg([person_score(p) for p in grades]):.1f}점")
    if base:
        tot = sum(f["importance"] for f in facts)
        bs = [100 * sum(x["score"] * fmap[x["fact_id"]]["importance"] for x in b["grades"] if x["fact_id"] in fmap) / tot
              for b in base]
        L.append(f"- **기준값(읽지 않음) 평균**: {avg(bs):.1f}점")
    L.append("")

    jd = Counter(a["join_decision"] for a in answers.values())
    L += ["## 3. 가입 판단", "", " · ".join(f"{k} {v}명" for k, v in jd.items()), ""]

    L += ["## 4. 치명적 오해 발언", ""]
    crit = [r for r in rows if r["critical"]]
    L += [f"- **{r['pid']}** ({r['fid']}) “{r['answer']}” — {r['rationale']}" for r in crit[:10]] or ["- 없음"]
    L.append("")

    L += ["## 5. 가상고객 예시 (읽고 남은 것 → 답)", ""]
    for pid in ["20대-09", "40대-06", "60대-15"]:
        if pid not in reads:
            continue
        p, r = ps[pid], reads[pid]
        L += [f"### {pid} · {p['age']}세 · 지식 {p['knowledge']} · {p['disposition']} · 점수 {person_score(pid):.1f}", "",
              f"첫인상: {r['first_impression']}", "", "읽고 남은 것:"]
        L += [f"{i}. {m}" for i, m in enumerate(r["memory"], 1)]
        L += ["", "| 문항 | 답 | 점수 | 채점 근거 |", "|---|---|---|---|"]
        for f in facts:
            x = grades[pid].get(f["fact_id"], {})
            a = next((a for a in answers[pid]["answers"] if a["fact_id"] == f["fact_id"]), {})
            L.append(f"| {f['fact_id']} | {a.get('answer', '')} | {x.get('score', '')} | {x.get('rationale', '')} |")
        L.append("")

    L += ["## 6. 모의창구와 다르게 한 점 (가정값)", "",
          "- 패널: Nemotron 데이터셋 대신 A안의 48명(배경 이야기·지식·성향) 사용",
          f"- 기억 개수: 모의창구는 금융 친숙도별로 다르게 주지만, 우리는 모두 {MEMORY_ITEMS}개로 고정 (근거 없는 규칙 제외)",
          "- 문서: 상품설명서 2~4쪽 전체 (1쪽 연락처·홍보 제외), 2단 편집을 블록 순서로 이음",
          "- 문항 6개: AI 자동 생성 (사람 검토 전)",
          f"- 모델: {SETTINGS['model']} (문항 생성·채점은 생각 켬, 가상고객은 생각 끔)", ""]
    (OUT / "report_b.md").write_text("\n".join(L), encoding="utf-8")
    print("→ results_b/report_b.md")


STAGES = {"questions": stage_questions, "read": stage_read, "answer": stage_answer,
          "grade": stage_grade, "baseline": stage_baseline, "report": stage_report}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=list(STAGES) + ["all"])
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    if not (OUT / "document.txt").exists():
        build_document()
    for name in (STAGES if args.stage == "all" else [args.stage]):
        print(f"== {name}", flush=True)
        STAGES[name]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
