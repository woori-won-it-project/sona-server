"""C안: 우리 기준(정보 경로 · 문장 단위 읽기 · 용어 이해 단계) + 모의창구식 '덮고 기억으로 답하기'.

  1. paths   : 정보 경로별로 상품 전체를 다루는 글 4종을 만든다
               약관 정독 / 해당 조항만 / 설명서만 / 설계사 말만(AI 생성, v2 지시문, 한 번 만들고 고정)
  2. read    : 사람마다 자기 경로 글을 문장 단위 읽기 규칙(꼼꼼함·성향, 04 와 같은 규칙)으로 읽고,
               '본 문장만' 가지고 머릿속에 남은 것 7줄을 적는다 (기억 줄 수는 모두 같음)
  3. answer  : 문서를 덮고 메모만 보고 B안과 같은 창구 질문 6개에 답한다 (용어 이해 단계는 인물 카드로 전달)
  4. grade   : B안 채점관 그대로 (1 / 0.5 / 0, 치명적 오해)
  5. report  : 경로별·연령대별·지식별 결과, 경로 가중(50/30/15/5) 결과, B안 기준값과 비교
실행 (persona-pilot 폴더에서): python scripts/c_hybrid.py all   또는  <stage>
결과: results_c/
"""

import argparse
import importlib.util
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_llm import SETTINGS, call_with_retry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results_c"
B_OUT = ROOT / "results_b"
WORKERS = 4


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mat = load("build_materials", "02_build_materials.py")   # 약관 조항 뽑기
bp = load("build_prompts", "04_build_prompts.py")         # 문장 단위 읽기 규칙
bm = load("b_modu_style", "b_modu_style.py")              # 메모로 답하기 · 채점

PATH_NAME = {p["id"]: p["name"] for p in SETTINGS["paths"]}
WEIGHT = {p["id"]: p["weight"] for p in SETTINGS["paths"]}
KNOW_TEXT = {"상": "보험 용어와 조건을 대체로 정확히 이해하는 편",
             "중": "보험 용어를 대략적으로만 아는 편",
             "하": "보험 용어를 잘 모르고, 비슷한 일상 말로 짐작하는 편"}


def jdump(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def jload(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------- 1. 경로별 글 ----------
AGENT_PROMPT = """당신은 은행 창구에서 보험을 파는 직원입니다. 아래 상품설명서 내용을 고객에게 설명하는 판매 화법을
4~6문장의 구어체로 작성하세요.
- 보장 내용 중심으로 말하고, 예외나 조건은 말하지 않거나, 말하더라도 "자세한 조건은 약관에 있어요"처럼
  구체적인 숫자나 항목 없이 한마디로만 넘어가세요.
- "무조건", "100%", "다 나와요"처럼 명백한 거짓 약속은 쓰지 마세요.
- 화법 문장만 출력하세요.

[상품설명서]
{doc}"""


def stage_paths() -> dict:
    arts = mat.split_articles(mat.load_main_terms())
    a = arts.__getitem__
    # 해당 조항만: 6개 질문(B안 facts)이 직접 걸린 조항
    clause = "\n".join([
        a(7),                                   # 암 주요치료 (합병증·호르몬 제외)
        a(11),                                  # 보험금 지급사유 (금액·횟수·50%)
        mat.paragraphs(a(12), [3, 4, 9, 10]),   # 최초 진단일·지급기간·연 1회·1년 내 50%
        mat.paragraphs(a(28), [5]),             # 갱신 보험료
        mat.paragraphs(a(40), [1]),             # 해약환급금
    ])
    full = "\n".join([
        "\n".join([mat.heading(a(2))] + mat.lines_starting(a(2), ("2. 지급사유 관련 용어",))
                  + mat.lines_starting(a(2), ("가. 최초 암진단확정일", "나. 보험금 지급기간", "다. 연간"))),
        a(3), a(7), a(8), a(11), mat.paragraphs(a(12), [1, 3, 4, 9, 10, 11, 12]),
        a(28), mat.paragraphs(a(31), [5]), a(40),
    ])
    guide = bm.document()
    prev_path = OUT / "path_docs.json"
    prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else {}
    if prev.get("agent_talk"):
        agent = prev["agent_talk"]  # 한 번 만든 화법은 고정
    else:
        r = call_with_retry(AGENT_PROMPT.format(doc=guide), "c_agent_talk")
        agent = {"text": r["text"].strip().strip('"“”').strip(), "sources": ["AI 생성 (c_hybrid AGENT_PROMPT, v2 규칙)"]}
    docs = {
        "full_terms": {"text": full, "sources": ["제2조 2호", "제3조", "제7조", "제8조", "제11조", "제12조",
                                                  "제28조", "제31조⑤", "제40조"]},
        "clause_only": {"text": clause, "sources": ["제7조", "제11조", "제12조③④⑨⑩", "제28조⑤", "제40조①"]},
        "guide_only": {"text": guide, "sources": ["상품설명서 2~4쪽"]},
        "agent_talk": agent,
    }
    prev_path.write_text(json.dumps(docs, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in docs.items():
        print(f"{PATH_NAME[k]}: {len(v['text']):,}자")
    print("설계사 화법:", agent["text"])
    return docs


# ---------- 2. 읽기 (본 문장만으로 메모) ----------
READ_PROMPT = """{card}

이 보험에 대해 아래 내용을 접했습니다 ({path_name}).
아래 글은 이 사람이 실제로 보거나 들은 문장만 모은 것입니다 (놓친 문장은 빠져 있습니다).
이제 이 글은 다시 볼 수 없습니다.

머릿속에 남은 것을 이 사람의 말투로 정확히 {k}개 적으세요.
- 모든 내용을 기억하는 사람은 없습니다. 이 사람에게 인상 깊었던 것, 이해한 만큼만 남습니다.
- 아래 글에 없는 내용을 지어내지 마세요.
또 첫인상 한두 문장과, 이해하기 어려웠던 대목 2~3개(글의 문구 그대로 + 어려웠던 이유)를 적으세요.

[이 사람이 보거나 들은 내용]
{seen}"""


def card(p: dict) -> str:
    return (f"[당신은 이런 사람입니다]\n{p['age']}세. {p['backstory']}\n"
            f"보험 이해 수준: {KNOW_TEXT[p['knowledge']]}\n성향: {bm.DISPOSITION[p['disposition']]}")


# ---------- 기능적 제약 (2026-11-27 v2, 프롬프트가 아니라 코드가 강제) ----------
# ① 꼼꼼함 → 메모 최대 줄 수. 꼼꼼함 0.30 이하 5줄 ~ 0.75 이상 10줄, 사이는 비례. AI 가 더 써도 코드가 앞 N줄만 남긴다.
MEMO_MIN, MEMO_MAX, DIL_LO, DIL_HI = 5, 10, 0.30, 0.75


def memory_lines(diligence: float) -> int:
    t = min(1.0, max(0.0, (diligence - DIL_LO) / (DIL_HI - DIL_LO)))
    return round(MEMO_MIN + t * (MEMO_MAX - MEMO_MIN))


# ② 용어 이해 단계 B → 정의·설명 문장을 건너뜀. 하 = 모두 건너뜀, 중 = 절반(사람·문장 시드로 결정), 상 = 건너뛰지 않음
DEF_MARKERS = ("이라 함은", "라 함은", "란,", "이란 ", "란 ", "을 말합니다", "를 말합니다", "을 말하며", "를 말하며",
               "을 의미합니다", "를 의미합니다", "을 의미하며")
DEF_SKIP = {"상": 0.0, "중": 0.5, "하": 1.0}


def is_definition(s: dict) -> bool:
    t = s["text"]
    box = s["format"] == "aside" and t.startswith("(") and not t.startswith(("(예시)", "(이하"))
    item = t[:3] in ("가. ", "나. ", "다. ") and ":" in t[:30]          # 제2조 용어의 정의 각 목
    return box or item or any(m in t for m in DEF_MARKERS)


def hide_definitions(p: dict, sentences: list[dict]) -> int:
    rate, hidden = DEF_SKIP[p["knowledge"]], 0
    for s in sentences:
        if s["read"] and is_definition(s) and s["i"] > 0:
            if bp.sentence_rng(int(p["seed"]), "C_DEF", s["i"]).random() < rate:
                s["read"], s["skipped_as_definition"], hidden = False, True, hidden + 1
    return hidden


# ③ 용어 이해 단계 A → 읽는 글 속 핵심 용어 첫 등장 바로 뒤에 그 사람이 아는 뜻을 괄호로 붙인다 (상은 붙이지 않음)
GLOSSARY = json.loads((ROOT / "data" / "glossary.json").read_text(encoding="utf-8"))


def add_glosses(p: dict, text: str) -> tuple[str, list[str]]:
    level = p["knowledge"]
    if level == "상":
        return text, []
    added = []
    for term, t in GLOSSARY.items():
        meaning = t.get(level)
        if not meaning:
            continue
        for variant in dict.fromkeys([term, term.replace(" ", "")]):   # "암 주요치료" / "암주요치료"
            i = text.find(variant)
            if i >= 0:
                j = i + len(variant)
                text = text[:j] + f"(내가 아는 뜻: {meaning})" + text[j:]
                added.append(term)
                break
    return text, added


# ---------- v3 물리적 제약 (2026-11-27): 정보를 '빼기'만 한다. 무엇을 믿을지는 AI 가 남은 정보로 짐작 ----------
# v2 의 ② 정의 건너뛰기 · ③ 잘못 아는 뜻 붙이기 · ① 메모 줄 수는 쓰지 않는다 (함수는 기록용으로 남김)

# (1) 긴 문장 자르기: 용어 이해 단계별로 한 문장에서 읽을 수 있는 글자 수. 넘으면 앞부분만 남는다 (가정값)
SENTENCE_CHARS = {"하": 40, "중": 70, "상": None}


def truncate_long(p: dict, sentences: list[dict]) -> int:
    limit, cut = SENTENCE_CHARS[p["knowledge"]], 0
    if limit is None:
        return 0
    for s in sentences:
        if s["read"] and len(s["text"]) > limit:
            s["text_full"], s["text"], cut = s["text"], s["text"][:limit] + "…", cut + 1
    return cut


# (2) 모르는 용어 가리기: 어려운 용어를 □□ 로 바꿔 보여 준다. 하 = 전부, 중 = 절반(사람·용어 시드), 상 = 안 가림 (가정값)
HARD_TERMS = ["호르몬 관련 치료제", "최초 암진단확정일", "보험금 지급기간", "암보장개시일", "암 주요치료",
              "비급여", "전액본인부담", "항암약물치료", "항암방사선치료", "항암중입자방사선치료", "해약환급금",
              "납입최고", "갱신계약", "최초계약", "계약자적립액", "기타피부암", "보험가입금액"]
MASK_RATE = {"상": 0.0, "중": 0.5, "하": 1.0}


def mask_terms(p: dict, text: str) -> tuple[str, list[str]]:
    rate, masked = MASK_RATE[p["knowledge"]], []
    for i, term in enumerate(sorted(HARD_TERMS, key=len, reverse=True)):   # 긴 용어부터 (부분 겹침 방지)
        if bp.sentence_rng(int(p["seed"]), "C_MASK:" + term, i).random() >= rate:
            continue
        hit = False
        for variant in dict.fromkeys([term, term.replace(" ", "")]):       # "암 주요치료" / "암주요치료"
            if variant in text:
                text, hit = text.replace(variant, "□□"), True
        if hit:
            masked.append(term)
    return text, masked


# (3) 메모 글자 수 제한: 꼼꼼함 0.30 이하 150자 ~ 0.75 이상 400자, 비례. 코드가 앞에서부터 자른다 (가정값)
MEMO_CHARS_MIN, MEMO_CHARS_MAX = 150, 400


def memo_budget(diligence: float) -> int:
    t = min(1.0, max(0.0, (diligence - DIL_LO) / (DIL_HI - DIL_LO)))
    return round(MEMO_CHARS_MIN + t * (MEMO_CHARS_MAX - MEMO_CHARS_MIN))


def cut_memo(memory: list[str], budget: int) -> list[str]:
    out, used = [], 0
    for m in memory:
        if used >= budget:
            break
        room = budget - used
        out.append(m if len(m) <= room else m[:room] + "…")
        used += min(len(m), room)
    return out


READ_PROMPT_V3 = """{card}

이 보험에 대해 아래 내용을 접했습니다 ({path_name}).
아래 글은 이 사람이 실제로 보거나 들은 부분만 모은 것입니다. 놓친 문장은 빠져 있고, 끝까지 읽지 못한 문장은 '…'로 끊겨 있으며,
뜻을 모르는 낱말은 '□□'로 보입니다. 이제 이 글은 다시 볼 수 없습니다.

머릿속에 남은 것을 이 사람의 말투로 짧게 여러 줄 적으세요. 전체 {budget}자를 넘지 않게 쓰세요.
- 모든 내용을 기억하는 사람은 없습니다. 이 사람에게 인상 깊었던 것, 이해한 만큼만 남습니다.
- 아래 글에 없는 내용을 지어내지 마세요.
또 첫인상 한두 문장과, 이해하기 어려웠던 대목 2~3개(글의 문구 그대로 + 어려웠던 이유)를 적으세요.

[이 사람이 보거나 들은 내용]
{seen}"""


# (4) 내용 단위 가리기 (2026-11-27 v4, 꼼꼼함 보강): 같은 내용이 원문 여러 곳에 반복돼 문장 단위로 가려도
#     한 곳은 보게 되는 문제를 막는다. 내용마다 볼지 말지를 사람마다 '한 번만' 정하고, 못 보면 그 내용이 나오는
#     모든 문장을 가린다. 확률 = 0.2 + 꼼꼼함 (최대 1, 가정값). 내용 묶음은 6개 질문에 걸린 것만.
CONTENT_UNITS = {
    "1년 내 50% 감액": r"50%|500만원|500 만원|1 ?년 경과시점 전일|2,500만원",
    "호르몬제 제외": r"호르몬",
    "합병증·후유증 제외": r"합병증|후유증",
    "지급기간 10년·최초 진단일 기준": r"10 ?년까지|최대 10 ?년|10차년도|최초 암진단확정일",
    "연 1회·최대 10회": r"연간 1 ?회|최대 10 ?회",
    "비급여 2,000만원": r"2,000만원|2,000 만원",
    "해약환급금 적음": r"해약환급금|환급률|해약 환급금",
    "갱신 보험료 인상": r"인상될 수|보험요율",
}
UNIT_BASE = 0.2


def hide_content_units(p: dict, sentences: list[dict]) -> list[str]:
    import re
    p_catch = min(1.0, UNIT_BASE + float(p["diligence"]))
    missed = []
    for i, (unit, rx) in enumerate(CONTENT_UNITS.items()):
        if bp.sentence_rng(int(p["seed"]), "C_UNIT:" + unit, i).random() < p_catch:
            continue  # 이 내용은 봤다
        missed.append(unit)
        for s in sentences:
            if s["read"] and re.search(rx, s["text"]):
                s["read"], s["hidden_unit"] = False, unit
    return missed


def read_one(p: dict, docs: dict) -> dict:
    sentences = bp.read_text(p, "C_DOC", docs[p["path"]]["text"])          # 기존 규칙: 꼼꼼함·위치·각주
    missed_units = hide_content_units(p, sentences)                         # (4) 꼼꼼함: 내용 단위로 놓침
    cut = truncate_long(p, sentences)                                        # (1)
    seen, masked = mask_terms(p, "\n".join(s["text"] for s in sentences if s["read"]))   # (2)
    budget = memo_budget(float(p["diligence"]))                              # (3)
    d = bm.call_json(READ_PROMPT_V3.format(card=card(p), path_name=PATH_NAME[p["path"]], budget=budget, seen=seen),
                     f"c_read:{p['person_id']}", bm.READ_SCHEMA, max_tokens=4000)
    raw_chars = sum(len(m) for m in d["memory"])
    d["memory"] = cut_memo(d["memory"], budget)                              # 코드가 강제: 글자 수 초과분은 버린다
    return {"person_id": p["person_id"], "path": p["path"], "read_count": sum(s["read"] for s in sentences),
            "total": len(sentences), "missed_units": missed_units, "sentences_cut": cut, "masked_terms": masked,
            "memo_budget": budget, "memo_chars_written": raw_chars, "sentences": sentences, **d}


def stage_read() -> None:
    docs = json.loads((OUT / "path_docs.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(WORKERS) as pool:
        rows = list(pool.map(lambda p: read_one(p, docs), bm.people()))
    jdump(OUT / "reads.jsonl", rows)
    for path in PATH_NAME:
        sel = [r for r in rows if r["path"] == path]
        rate = sum(r["read_count"] for r in sel) / max(1, sum(r["total"] for r in sel))
        print(f"{PATH_NAME[path]}: 읽은 문장 {rate:.0%}")


# ---------- 3. 답하기 · 4. 채점 ----------
def stage_answer() -> None:
    facts = json.loads((B_OUT / "facts.json").read_text(encoding="utf-8"))
    reads = {r["person_id"]: r for r in jload(OUT / "reads.jsonl")}
    ps = bm.people()
    qs = "\n".join(f"{f['fact_id']}. {f['question']}" for f in facts)

    def one(p):
        mem = "\n".join(f"- {m}" for m in reads[p["person_id"]]["memory"])
        return bm.call_json(bm.ANSWER_PROMPT.format(card=card(p), memory=mem, questions=qs),
                            f"c_answer:{p['person_id']}", bm.ANSWER_SCHEMA, max_tokens=4000)

    with ThreadPoolExecutor(WORKERS) as pool:
        res = list(pool.map(one, ps))
    jdump(OUT / "answers.jsonl", [{"person_id": p["person_id"], **d} for p, d in zip(ps, res)])
    print(f"답변 {len(res)}명")


def stage_grade() -> None:
    facts = json.loads((B_OUT / "facts.json").read_text(encoding="utf-8"))
    answers = jload(OUT / "answers.jsonl")
    with ThreadPoolExecutor(WORKERS) as pool:
        res = list(pool.map(lambda a: bm.grade_one(a["answers"], facts, f"c_grade:{a['person_id']}"), answers))
    jdump(OUT / "grades.jsonl", [{"person_id": a["person_id"], "grades": g} for a, g in zip(answers, res)])
    print(f"채점 {len(res)}명")


# ---------- 5. 리포트 ----------
def pct(x: float) -> str:
    return f"{x:.0%}"


def avg(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def stage_report() -> None:
    facts = json.loads((B_OUT / "facts.json").read_text(encoding="utf-8"))
    fmap = {f["fact_id"]: f for f in facts}
    ps = {p["person_id"]: p for p in bm.people()}
    reads = {r["person_id"]: r for r in jload(OUT / "reads.jsonl")}
    grades = {g["person_id"]: {x["fact_id"]: x for x in g["grades"] if x["fact_id"] in fmap}
              for g in jload(OUT / "grades.jsonl")}
    answers = {a["person_id"]: a for a in jload(OUT / "answers.jsonl")}
    tot_w = sum(f["importance"] for f in facts)

    def score_of(gs) -> float:
        return 100 * sum(x["score"] * fmap[x["fact_id"]]["importance"] for x in gs if x["fact_id"] in fmap) / tot_w

    def score(pid: str) -> float:
        return score_of(grades[pid].values())

    base = jload(B_OUT / "baseline.jsonl") if (B_OUT / "baseline.jsonl").exists() else []
    b_grades = jload(B_OUT / "grades.jsonl") if (B_OUT / "grades.jsonl").exists() else []
    base_score = avg(score_of(b["grades"]) for b in base)
    b_score = avg(score_of(g["grades"]) for g in b_grades)

    path_avg = {pth: avg(score(p) for p in grades if ps[p]["path"] == pth) for pth in PATH_NAME}

    # 실제 비율 가중 (균등 배정이므로 칸 평균에 실제 비율을 곱해 합친다, 2026-11-27)
    #   연령대 안: Σ 경로 가중치 × Σ 연령대별 상중하 실측 비율(보험연구원 2019) × 칸 평균
    #   연령대 사이: 2024 금융이해력 조사 응답자 구성비 (20대 16.7 · 40대 18.6 · 60대 18.4 %)
    import yaml
    know_ratio = yaml.safe_load((ROOT / "config" / "age_rules.yaml").read_text(encoding="utf-8"))["knowledge_by_age"]
    age_share = {"20대": 16.7, "30대": 15.8, "40대": 18.6, "50대": 20.8, "60대": 18.4, "70대": 9.7}

    def cell_avg(age, pth, lv):
        return avg(score(p) for p in grades if ps[p]["age_group"] == age and ps[p]["path"] == pth and ps[p]["knowledge"] == lv)

    age_weighted = {age: sum(WEIGHT[pth] * know_ratio[age][lv] * cell_avg(age, pth, lv)
                             for pth in PATH_NAME for lv in ("상", "중", "하"))
                    for age in SETTINGS["age_groups"]}
    share_sum = sum(age_share[a] for a in SETTINGS["age_groups"])
    weighted = sum(age_share[a] / share_sum * age_weighted[a] for a in SETTINGS["age_groups"])

    L = ["# C안 결과: 우리 기준 + 덮고 기억으로 답하기", "",
         "> 가상고객 48명 LLM 시뮬레이션 결과입니다. 실제 소비자 조사가 아닙니다.",
         "> 흐름: 정보 경로별 글 → 문장 단위 읽기(꼼꼼함·성향) → 본 문장만으로 메모 7줄 → 문서 덮고 창구 질문 6개 답 → 채점.",
         "> 기준: 꼼꼼함·용어 이해 단계는 보험연구원 2019 설문 근거, 경로 비율 50/30/15/5 는 가정값 (EVIDENCE.md 8절).", "",
         "## 1. 한눈에", "",
         "| 구분 | 평균 이해도 (100점, 중요도 가중) |", "|---|---|",
         f"| C안 전체 (실제 비율 가중: 경로 50/30/15/5 × 연령대별 상중하 × 연령 구성비) | **{weighted:.1f}점** |",
         *[f"| └ {a} (실제 비율 가중) | {age_weighted[a]:.1f}점 |" for a in SETTINGS["age_groups"]],
         f"| C안 전체 (가중 없음) | {avg(score(p) for p in grades):.1f}점 |",
         f"| B안 (모두 설명서 전체를 읽음) | {b_score:.1f}점 |",
         f"| 기준값 (아무것도 안 읽음, B안에서 측정) | {base_score:.1f}점 |", ""]

    L += ["## 2. 정보 경로별", "", "| 경로 | 가중치 | 평균 읽은 문장 | 평균 이해도 | 치명적 오해 |", "|---|---|---|---|---|"]
    for pth in PATH_NAME:
        sel = [p for p in grades if ps[p]["path"] == pth]
        rr = avg(reads[p]["read_count"] / max(1, reads[p]["total"]) for p in sel)
        crit = sum(x["critical"] for p in sel for x in grades[p].values())
        L.append(f"| {PATH_NAME[pth]} | {pct(WEIGHT[pth])} | {pct(rr)} | {path_avg[pth]:.1f}점 | {crit}건 |")
    L.append("")

    L += ["## 2-1. 용어 이해 단계 × 경로 (같은 경로 안에서 비교, 평균 이해도)", "",
          "| 용어 이해 | " + " | ".join(PATH_NAME.values()) + " | 전체 (균등) |", "|---|" + "---|" * (len(PATH_NAME) + 1)]
    for lv in ("상", "중", "하"):
        row = [lv] + [f"{avg(score(p) for p in grades if ps[p]['path'] == pth and ps[p]['knowledge'] == lv):.1f}"
                      for pth in PATH_NAME]
        row.append(f"{avg(score(p) for p in grades if ps[p]['knowledge'] == lv):.1f}")
        L.append("| " + " | ".join(row) + " |")
    L += ["", "칸마다 인원이 같으므로(연령대 3 × 2명 = 6명) 경로 효과가 섞이지 않는다.", ""]

    L += ["## 3. 문항 × 경로 (만점 비율 / 치명적 오해 건수)", "",
          "| 문항 | " + " | ".join(PATH_NAME.values()) + " | 전체 |", "|---|" + "---|" * (len(PATH_NAME) + 1)]
    for f in facts:
        row = [f"{f['fact_id']} {f['category']}"]
        for pth in PATH_NAME:
            sel = [grades[p][f["fact_id"]] for p in grades if ps[p]["path"] == pth and f["fact_id"] in grades[p]]
            row.append(f"{pct(avg(x['score'] == 1 for x in sel))} / {sum(x['critical'] for x in sel)}")
        allx = [grades[p][f["fact_id"]] for p in grades if f["fact_id"] in grades[p]]
        row.append(f"{pct(avg(x['score'] == 1 for x in allx))} / {sum(x['critical'] for x in allx)}")
        L.append("| " + " | ".join(row) + " |")
    L += ["", *[f"- **{f['fact_id']}** {f['question']} → {f['answer']}" for f in facts], ""]

    L += ["## 4. 연령대 · 용어 이해 단계 · 성향별 평균 이해도", ""]
    for key, name, vals in [("age_group", "연령대", SETTINGS["age_groups"]), ("knowledge", "용어 이해", ["상", "중", "하"]),
                            ("disposition", "성향", ["optimistic", "cautious"])]:
        parts = []
        for v in vals:
            sel = [p for p in grades if ps[p][key] == v]
            if sel:
                parts.append(f"{v} {avg(score(p) for p in sel):.1f}점 ({len(sel)}명)")
        L.append(f"- **{name}**: " + " · ".join(parts))
    L.append("- 연령대 평균 꼼꼼함: " + " · ".join(
        f"{g} {avg(float(ps[p]['diligence']) for p in ps if ps[p]['age_group'] == g):.2f}" for g in SETTINGS["age_groups"]))
    lv3 = [v for v in ["상", "중", "하"] if any(ps[p]['knowledge'] == v for p in reads)]
    L.append("- 연령대 평균 메모 글자 한도: " + " · ".join(
        f"{g} {avg(reads[p].get('memo_budget', 0) for p in reads if ps[p]['age_group'] == g):.0f}자"
        for g in SETTINGS["age_groups"]))
    L.append("- 연령대 평균 놓친 내용 수(8개 중): " + " · ".join(
        f"{g} {avg(len(reads[p].get('missed_units', [])) for p in reads if ps[p]['age_group'] == g):.1f}개"
        for g in SETTINGS["age_groups"]))
    L.append("- 용어 단계별 잘린 긴 문장(평균): " + " · ".join(
        f"{v} {avg(reads[p].get('sentences_cut', 0) for p in reads if ps[p]['knowledge'] == v):.1f}개" for v in lv3))
    L.append("- 용어 단계별 가린 용어 수(평균): " + " · ".join(
        f"{v} {avg(len(reads[p].get('masked_terms', [])) for p in reads if ps[p]['knowledge'] == v):.1f}개" for v in lv3))
    try:
        import statistics as st
        ids = list(grades)
        L.append(f"- 꼼꼼함과 점수의 상관: {st.correlation([float(ps[p]['diligence']) for p in ids], [score(p) for p in ids]):.2f}"
                 f" / 메모 글자 한도와 점수의 상관: "
                 f"{st.correlation([reads[p].get('memo_budget', 0) for p in ids], [score(p) for p in ids]):.2f}")
    except Exception:
        pass
    L.append("")

    jd = Counter(a["join_decision"] for a in answers.values())
    L += ["## 5. 가입 판단", "", " · ".join(f"{k} {v}명" for k, v in jd.items()), ""]

    L += ["## 6. 가정값", "",
          "- 경로 비율 50/30/15/5: 근거 없음 (설계사 의존이 크다는 방향만 자료와 일치)",
          "- 경로별 글: 해당 조항만 = 6문항이 걸린 조항, 약관 정독 = 관련 조항 전체 + 정의, 설계사 말만 = AI 생성 화법(v2 규칙)",
          "- 문장 읽기 규칙 가중치(위치·형식·종류): A안 명세서의 가정값 그대로",
          f"- 긴 문장 자르기: 한 문장에서 읽는 글자 수 하 {SENTENCE_CHARS['하']}자 · 중 {SENTENCE_CHARS['중']}자 · 상 끝까지 (가정)",
          f"- 모르는 용어 가리기: 어려운 용어 {len(HARD_TERMS)}개를 □□ 로, 하 전부 · 중 절반 · 상 안 가림 (가정)",
          f"- 메모 글자 수: 꼼꼼함 {DIL_LO} 이하 {MEMO_CHARS_MIN}자 ~ {DIL_HI} 이상 {MEMO_CHARS_MAX}자 비례 (코드가 강제, 가정)",
          f"- 내용 단위 가리기: 핵심 내용 {len(CONTENT_UNITS)}개마다 볼 확률 {UNIT_BASE} + 꼼꼼함, 못 보면 그 내용이 나오는 모든 문장을 가림 (가정)",
          "- 쓰지 않음: 잘못 아는 뜻 붙이기(시나리오), 정의 건너뛰기, 메모 줄 수 제한",
          "- 문항 6개: B안에서 AI가 자동 생성 (사람 검토 전)", ""]
    (OUT / "report_c.md").write_text("\n".join(L), encoding="utf-8")
    print("→ results_c/report_c.md")


STAGES = {"paths": stage_paths, "read": stage_read, "answer": stage_answer, "grade": stage_grade, "report": stage_report}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=list(STAGES) + ["all"])
    ap.add_argument("--out", default="results_c", help="결과 폴더 (반복 실행용, 예: results_c_rep2)")
    args = ap.parse_args()
    global OUT
    OUT = ROOT / args.out
    OUT.mkdir(exist_ok=True)
    if not (OUT / "path_docs.json").exists() and (ROOT / "results_c" / "path_docs.json").exists():
        # 반복 실행은 같은 경로별 글(같은 설계사 화법)을 써야 하므로 복사해 온다
        (OUT / "path_docs.json").write_text((ROOT / "results_c" / "path_docs.json").read_text(encoding="utf-8"),
                                            encoding="utf-8")
    for name in (STAGES if args.stage == "all" else [args.stage]):
        print(f"== {name}", flush=True)
        STAGES[name]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
