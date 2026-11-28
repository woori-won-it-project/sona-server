"""4-7 문장 단위 읽기 + 4-8 프롬프트 조립. [C6]

사람마다 그 사람의 경로 글을 문장으로 나누고, 꼼꼼함·성향에 따라 문장마다 읽을지 정한다.
못 본 문장은 프롬프트에 넣지 않는다. AI 는 호출하지 않는다.

실행: python scripts/04_build_prompts.py            (persona-pilot 폴더에서)
      python scripts/04_build_prompts.py --draft    (AI 생성 자료가 아직 없어도 자리표시로 채워 샘플만 확인)
결과: results/prompts/prompts.jsonl   (48명 × 4문항 = 192줄)
      results/prompts/c6_samples.md   (서로 다른 조건의 프롬프트 샘플 5개, C6 검토용)
"""

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "results" / "prompts"
SETTINGS = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
RULES = yaml.safe_load((ROOT / "config" / "reading_rules.yaml").read_text(encoding="utf-8"))

PATH_NAMES = {p["id"]: p["name"] for p in SETTINGS["paths"]}
MISSING = "(아직 생성되지 않음)"

TEMPLATE = """[배경 이야기]
{backstory}

[성향]
{disposition}

[당신이 읽은 글]  ({path_name})
{read_text}

[용어]
{terms}

[상황]
{question}

{instruction}"""

# 답 지시문. allow_undetermined: false 이면 예/아니요 중 하나를 반드시 고르게 한다 (사용자 결정 2026-11-26)
INSTRUCTION_WITH_UNDETERMINED = """위 정보만으로 판단하세요. 위에 없는 내용은 모르는 것으로 합니다.
읽은 글에 근거가 있다면 그 문장을 그대로 인용하세요.
JSON으로만 답하세요:
{"answer": "예|아니요|판단 불가", "reason": "1~2문장", "quoted": ["인용 문장"], "confidence": 1~5}"""

# v1 (폐기): "당신이 읽은 글과 용어, 그리고 당신의 생각을 바탕으로 판단하세요." → 아무것도 안 읽은 기준값에서
#    AI 가 보험 일반 상식으로 40번 중 38번 정답 → 읽은 글의 영향을 잴 수 없어 v2 로 교체
INSTRUCTION_FORCED = """당신은 보험에 대해 따로 공부한 적이 없는 일반인입니다.
보험에 관한 일반 상식이나 다른 보험 상품에 대한 지식은 쓰지 말고, 위에서 읽은 글과 용어 설명만 가지고 짐작하세요.
확실하지 않더라도 '예'와 '아니요' 중 더 그럴 것 같다고 생각하는 쪽을 반드시 하나 고르세요.
읽은 글에 근거가 있다면 그 문장을 그대로 인용하세요.
JSON으로만 답하세요:
{"answer": "예|아니요", "reason": "1~2문장", "quoted": ["인용 문장"], "confidence": 1~5}"""

ALLOW_UNDET = SETTINGS.get("allow_undetermined", True)
INSTRUCTION = INSTRUCTION_WITH_UNDETERMINED if ALLOW_UNDET else INSTRUCTION_FORCED
ANSWER_CHOICES = ["예", "아니요", "판단 불가"] if ALLOW_UNDET else ["예", "아니요"]

# 05 에서 structured outputs 로 쓰는 응답 모양 (명세서 4-8 의 JSON 형식과 같음)
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "enum": ANSWER_CHOICES},
        "reason": {"type": "string"},
        "quoted": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
    },
    "required": ["answer", "reason", "quoted", "confidence"],
    "additionalProperties": False,
}


# ---------- 문장 나누기 ----------
HEADING = re.compile(r"^(제\s*\d+\s*조\s*【[^】]+】)\s*")
NOTE_MARK = "❶❷❸❹❺❻❼❽❾❿⓫⓬⓭⓮⓯"  # 설명서 안내문 번호 (유니코드 구간이 둘로 나뉘어 있어 글자로 적음)
# "다. 연간: ..." 처럼 줄 맨 앞의 목 번호(가. 나. 다.)는 문장 끝이 아니므로, 앞에 한글이 한 글자 더 있을 때만 자른다
SENT_END = re.compile(rf"(?<=[가-힣][다요음함됨임원])\.\s+|(?<=\?)\s+|\s+(?=[{NOTE_MARK}]\s)")


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = HEADING.match(line)
        if m:  # "제7조 【...】 본문" 은 조 제목과 본문을 나눈다
            out.append(m.group(1))
            line = line[m.end():]
            if not line:
                continue
        parts = [p.strip() for p in SENT_END.split(line) if p and p.strip()]
        # 나눌 때 빠진 마침표를 되돌린다
        for i, p in enumerate(parts):
            if i < len(parts) - 1 and re.search(r"[다요음함됨임원]$", p):
                p += "."
            out.append(p)
    return out


# ---------- 문장 종류 ----------
def sentence_format(s: str) -> str:
    if HEADING.fullmatch(s) or s.endswith("?") or (s.startswith("[") and s.endswith("]")) \
            or re.fullmatch(r"\[[^\]]+\].*", s) and len(s) < 40 or (s.startswith("※") and len(s) <= 25):
        return "heading"
    if s.startswith(("(", "※", "（")):
        return "aside"  # 설명 상자, 예시, 각주
    return "normal"


def sentence_kind(s: str) -> str:
    if any(k in s for k in RULES["kind"]["exception"]["keywords"]):
        return "exception"  # 예외 문장이 우선 (예: "다만 ... 50%를 지급")
    if any(k in s for k in RULES["kind"]["coverage"]["keywords"]):
        return "coverage"
    return "other"


def read_probability(i: int, n: int, s: str, diligence: float, disposition: str) -> tuple[float, str, str]:
    budget = RULES["budget_base"] + RULES["budget_slope"] * diligence
    pos = i / (n - 1) if n > 1 else 0.0
    full, end = RULES["position"]["full_until"], RULES["position"]["end_factor"]
    position = 1.0 if pos <= full else 1.0 - (1.0 - end) * (pos - full) / (1.0 - full)

    fmt = sentence_format(s)
    form = RULES["format"]["heading"] if fmt == "heading" else RULES["format"]["aside"] if fmt == "aside" else 1.0

    kind = sentence_kind(s)
    k = RULES["kind"]
    if kind == "coverage":
        kind_f = k["coverage"]["optimistic_factor"] if disposition == "optimistic" else k["coverage"]["factor"]
    elif kind == "exception":
        kind_f = k["exception"]["base"] + k["exception"]["slope"] * diligence
        if disposition == "cautious":
            kind_f *= k["exception"]["cautious_extra"]
    else:
        kind_f = 1.0
    return min(1.0, budget * position * form * kind_f), fmt, kind


def sentence_rng(person_seed: int, question_id: str, i: int) -> random.Random:
    # 시드 = 사람 시드 + 문항 + 문장 순번. 같은 사람·같은 글이면 언제나 같은 문장을 읽는다
    h = hashlib.sha256(f"{person_seed}:{question_id}:{i}".encode()).hexdigest()[:12]
    return random.Random(int(h, 16))


def read_text(person: dict, question_id: str, text: str) -> list[dict]:
    sentences = split_sentences(text)
    n = len(sentences)
    rows = []
    for i, s in enumerate(sentences):
        p, fmt, kind = read_probability(i, n, s, float(person["diligence"]), person["disposition"])
        if i == 0 and RULES["first_sentence_always_read"]:
            p = 1.0
        read = sentence_rng(int(person["seed"]), question_id, i).random() < p
        rows.append({"i": i, "text": s, "format": fmt, "kind": kind, "p": round(p, 3), "read": read})
    return rows


# ---------- 프롬프트 ----------
def terms_block(glossary: dict, question_id: str, level: str) -> tuple[str, bool]:
    lines, missing = [], False
    for name, t in glossary.items():
        if question_id not in t["questions"]:
            continue
        meaning = t.get(level)
        if not meaning:
            missing, meaning = True, MISSING
        lines.append(f"- {name}: {meaning}")
    return "\n".join(lines), missing


def build_all(draft: bool) -> list[dict]:
    texts = json.loads((DATA / "path_texts.json").read_text(encoding="utf-8"))
    questions = json.loads((DATA / "questions.json").read_text(encoding="utf-8"))
    glossary = json.loads((DATA / "glossary.json").read_text(encoding="utf-8"))
    with (DATA / "personas.csv").open(encoding="utf-8-sig") as f:
        people = list(csv.DictReader(f))

    items = []
    for person in people:
        for q in questions:
            missing = []
            path_text = texts[q["clause_id"]].get(person["path"])
            if not path_text:
                missing.append("agent_talk")
                path_text = {"text": MISSING}
            sentences = read_text(person, q["question_id"], path_text["text"])
            terms, terms_missing = terms_block(glossary, q["question_id"], person["knowledge"])
            if terms_missing:
                missing.append("glossary")
            backstory = person.get("backstory") or ""
            if not backstory:
                missing.append("backstory")
                backstory = MISSING
            prompt = TEMPLATE.format(
                backstory=backstory,
                disposition=SETTINGS["dispositions"][person["disposition"]],
                path_name=PATH_NAMES[person["path"]],
                read_text="\n".join(s["text"] for s in sentences if s["read"]),
                terms=terms,
                question=q["question"],
                instruction=INSTRUCTION,
            )
            items.append({
                "person_id": person["person_id"], "question_id": q["question_id"], "path": person["path"],
                "age_group": person["age_group"], "knowledge": person["knowledge"],
                "disposition": person["disposition"], "diligence": float(person["diligence"]),
                "prompt": prompt, "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16],
                "sentences": sentences, "read_count": sum(s["read"] for s in sentences),
                "total": len(sentences), "missing": missing,
            })
    if not draft:
        not_ready = sorted({m for it in items for m in it["missing"]})
        if not_ready:
            raise SystemExit(f"아직 생성되지 않은 자료가 있습니다: {not_ready}. "
                             "02b_generate_ai.py 를 먼저 실행하거나, 샘플만 보려면 --draft 를 붙이세요.")
    return items


def pick_samples(items: list[dict]) -> list[dict]:
    """경로·문항·연령대·지식·성향이 서로 겹치지 않게 5개를 고른다."""
    wanted = [
        ("full_terms", "Q1"), ("clause_only", "Q2"), ("guide_only", "Q1"), ("agent_talk", "Q2"), ("guide_only", "Q3"),
    ]
    used_people, picked = set(), []
    for path, qid in wanted:
        cands = [it for it in items if it["path"] == path and it["question_id"] == qid
                 and it["person_id"] not in used_people
                 and (it["age_group"], it["knowledge"], it["disposition"]) not in
                 {(p["age_group"], p["knowledge"], p["disposition"]) for p in picked}]
        if cands:
            picked.append(cands[0])
            used_people.add(cands[0]["person_id"])
    return picked


def write_samples(samples: list[dict]) -> None:
    lines = ["# C6 프롬프트 샘플 (AI 호출 전)", ""]
    for n, it in enumerate(samples, 1):
        skipped = [s for s in it["sentences"] if not s["read"]]
        lines += [
            f"## 샘플 {n}: {it['person_id']} · {PATH_NAMES[it['path']]} · {it['question_id']}",
            f"- 지식 {it['knowledge']}, 성향 {it['disposition']}, 꼼꼼함 {it['diligence']}",
            f"- 읽은 문장 {it['read_count']} / {it['total']}" + (f", 아직 없는 자료: {it['missing']}" if it["missing"] else ""),
            "", "```", it["prompt"], "```", "",
            "<details><summary>못 본 문장 (확률)</summary>", "",
        ]
        lines += [f"- ({s['p']}, {s['kind']}/{s['format']}) {s['text']}" for s in skipped] or ["- 없음"]
        lines += ["", "</details>", ""]
    (OUT / "c6_samples.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true", help="AI 생성 자료가 없어도 자리표시로 채워 샘플 확인")
    args = ap.parse_args()
    items = build_all(args.draft)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "prompts.jsonl").open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    write_samples(pick_samples(items))

    # 경로·문항별 평균 읽은 비율
    print(f"{len(items)}개 프롬프트 → results/prompts/prompts.jsonl" + ("  (draft)" if args.draft else ""))
    for path in PATH_NAMES:
        row = []
        for q in sorted({it["question_id"] for it in items}):
            sel = [it for it in items if it["path"] == path and it["question_id"] == q]
            row.append(f"{q} {sum(it['read_count'] for it in sel) / sum(it['total'] for it in sel):.0%}")
        print(f"  {PATH_NAMES[path]:8} 읽은 문장 비율: " + ", ".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
