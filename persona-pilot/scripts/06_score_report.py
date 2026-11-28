"""4-10 채점·집계 + 5 결과 리포트.

실행: python scripts/06_score_report.py   (persona-pilot 폴더에서, 05 실행 후)
결과: results/scored.csv, results/report.md

채점: answer == answer_key → 정답, '판단 불가' → 판단 불가(오답과 별도), 그 밖 → 오답, failed → 미확인.
이 결과는 '가상고객 실험 결과'이며 실제 소비자 오해율이 아니다.
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA, RES = ROOT / "data", ROOT / "results"
SETTINGS = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
PATHS = [p["id"] for p in SETTINGS["paths"]]
PATH_NAME = {p["id"]: p["name"] for p in SETTINGS["paths"]}
WEIGHT = {p["id"]: p["weight"] for p in SETTINGS["paths"]}
DISP_NAME = {"optimistic": "낙관", "cautious": "신중"}

# 원인 분석용: 정답 근거 문장을 알아보는 표시어 (이 글자가 든 문장을 '정답 근거 문장'으로 본다)
EVIDENCE_KEYS = {
    "Q1": ["50%", "500만원"],          # 1년 내 진단 시 50% 지급
    "Q2": ["호르몬 관련 치료제"],        # 암 주요치료에서 제외
    "Q3": ["15일", "15 일"],            # 증권 받은 날부터 15일 이내
    # 독촉 기간이 끝나면 해지. '해지'만 쓰면 "해지에 관한 안내"(제목)·"해지 전에"(화법)까지 잡혀서 좁힘
    "Q4": ["다음 날에 계약이 해지", "다음날에 계약을 해지", "계약이 해지된다", "끝 나는 날의 다음 날에 계약이"],
}

# 비용 계산 (Claude Haiku 5.5, 프롬프트 10만 토큰 이하 요금, 달러/백만 토큰)
PRICE_IN, PRICE_OUT = 0.10, 0.50


def norm(s: str) -> str:
    """인용 검사용: 띄어쓰기·따옴표·문장부호 차이는 무시한다."""
    return re.sub(r"[\s\"'“”‘’.,·]", "", s)


def pct(n: int, d: int) -> str:
    return f"{n / d:.0%}" if d else "-"


def load() -> list[dict]:
    questions = {q["question_id"]: q for q in json.loads((DATA / "questions.json").read_text(encoding="utf-8"))}
    with (DATA / "personas.csv").open(encoding="utf-8-sig") as f:
        people = {p["person_id"]: p for p in csv.DictReader(f)}
    prompts = {(d["person_id"], d["question_id"]): d
               for d in map(json.loads, (RES / "prompts" / "prompts.jsonl").read_text(encoding="utf-8").splitlines())}
    rows = []
    for path in sorted((RES / "responses").glob("run*.jsonl")):
        for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()):
            q, p, pr = questions[r["question_id"]], people[r["person_id"]], prompts[(r["person_id"], r["question_id"])]
            if r["status"] != "ok":
                result = "미확인"
            elif r["answer"] == "판단 불가":
                result = "판단 불가"
            else:
                result = "정답" if r["answer"] == q["answer_key"] else "오답"

            read_norm = norm(" ".join(s["text"] for s in pr["sentences"] if s["read"]))
            terms_norm = norm(pr["prompt"].split("[용어]")[1].split("[상황]")[0])
            # 인용이 읽은 글에 없으면 무효. 단, [용어] 칸에서 인용한 것은 따로 센다 (프롬프트에 실제로 준 글이므로)
            quotes = [x for x in r["quoted"] if norm(x) and norm(x) not in read_norm]
            term_quotes = [x for x in quotes if norm(x) in terms_norm]
            bad_quotes = [x for x in quotes if norm(x) not in terms_norm]
            keys = EVIDENCE_KEYS[r["question_id"]]
            ev_all = [s for s in pr["sentences"] if any(k in s["text"] for k in keys)]
            rows.append({
                "run": r["run"], "person_id": r["person_id"], "question_id": r["question_id"],
                "type": q["type"], "age_group": p["age_group"], "path": p["path"], "knowledge": p["knowledge"],
                "disposition": p["disposition"], "diligence": float(p["diligence"]),
                "answer_key": q["answer_key"], "answer": r["answer"], "result": result,
                "confidence": r["confidence"], "reason": r["reason"], "quoted": r["quoted"],
                "invalid_quote": bool(bad_quotes), "term_quote": bool(term_quotes), "read_count": pr["read_count"], "total": pr["total"],
                "evidence_in_text": bool(ev_all), "evidence_seen": any(s["read"] for s in ev_all),
                "status": r["status"], "tries": r["tries"], "prompt": pr["prompt"],
                "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"],
            })
    return rows


# ---------- 집계 ----------
def rates(sel: list[dict]) -> dict:
    n = len([r for r in sel if r["result"] != "미확인"])
    c = Counter(r["result"] for r in sel)
    return {"n": n, "wrong": c["오답"] / n if n else 0, "undet": c["판단 불가"] / n if n else 0,
            "miss": (c["오답"] + c["판단 불가"]) / n if n else 0, "unknown": c["미확인"]}


def weighted(sel: list[dict], key: str) -> float:
    """경로 가중치(5/20/35/40%)로 가중한 비율. 경로마다 비율을 낸 뒤 가중합."""
    return sum(WEIGHT[p] * rates([r for r in sel if r["path"] == p])[key] for p in PATHS)


def table(header: list[str], body: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + \
           ["| " + " | ".join(str(x) for x in row) + " |" for row in body]


def f(x: float) -> str:
    return f"{x:.0%}"


def build_report(rows: list[dict]) -> str:
    qids = sorted({r["question_id"] for r in rows})
    qtype = {r["question_id"]: r["type"] for r in rows}
    L: list[str] = []
    L += ["# 페르소나 파일럿 결과 리포트 (A안)", "",
          "> **가상고객 실험 결과**입니다. 실제 소비자 오해율이 아닙니다.",
          "> 상품: 동양생명 무배당엔젤New 독특한암치료보험(갱신형) · 가상고객 48명 × 4문항 × 1회", "",
          "용어: **오답률** = 오답 / 응답, **판단 불가율** = 판단 불가 / 응답, **오해율** = (오답 + 판단 불가) / 응답.",
          "가중 = 정보 경로 가정 비율(약관 정독 5 · 해당 조항만 20 · 설명서만 35 · 설계사 말만 40%)로 가중한 값.", ""]

    # 1. 요약
    L += ["## 1. 요약", ""]
    body = []
    for q in qids:
        sel = [r for r in rows if r["question_id"] == q]
        rt = rates(sel)
        body.append([q, "분쟁" if qtype[q] == "dispute" else "대조군", f(rt["wrong"]), f(rt["undet"]), f(rt["miss"]),
                     f(weighted(sel, "wrong")), f(weighted(sel, "undet")), f(weighted(sel, "miss"))])
    L += table(["문항", "종류", "오답률", "판단 불가율", "오해율", "오답률(가중)", "판단 불가율(가중)", "오해율(가중)"], body)
    L.append("")
    for t, name in [("dispute", "분쟁 2문항"), ("control", "대조군 2문항")]:
        qs = [q for q in qids if qtype[q] == t]
        un = sum(rates([r for r in rows if r["question_id"] == q])["miss"] for q in qs) / len(qs)
        wt = sum(weighted([r for r in rows if r["question_id"] == q], "miss") for q in qs) / len(qs)
        uw = sum(rates([r for r in rows if r["question_id"] == q])["wrong"] for q in qs) / len(qs)
        ww = sum(weighted([r for r in rows if r["question_id"] == q], "wrong") for q in qs) / len(qs)
        L.append(f"- **{name} 평균**: 오해율 {f(un)} (가중 {f(wt)}), 오답률 {f(uw)} (가중 {f(ww)})")
    L += ["", "문항이 분쟁 2 + 대조군 2뿐이라 분쟁·대조군 차이는 **경향 확인 수준**으로만 해석합니다.", ""]

    # 2. 경로별
    L += ["## 2. 정보 경로별 오해율 (오답 + 판단 불가)", ""]
    body = []
    for p in PATHS:
        row = [PATH_NAME[p]]
        for q in qids:
            rt = rates([r for r in rows if r["path"] == p and r["question_id"] == q])
            row.append(f"{f(rt['miss'])} (오답 {f(rt['wrong'])})")
        body.append(row)
    L += table(["경로"] + qids, body) + ["", "각 칸은 12명(연령대 3 × 4명)의 결과입니다.", ""]

    # 3. 연령대·지식·성향
    L += ["## 3. 연령대·지식·성향별 오해율", ""]
    for key, name, values, label in [
        ("age_group", "연령대", SETTINGS["age_groups"], lambda v: v),
        ("knowledge", "지식", ["상", "중", "하"], lambda v: v),
        ("disposition", "성향", ["optimistic", "cautious"], lambda v: DISP_NAME[v]),
    ]:
        body = []
        for v in values:
            row = [label(v)]
            for q in qids:
                row.append(f(rates([r for r in rows if r[key] == v and r["question_id"] == q])["miss"]))
            row.append(f(rates([r for r in rows if r[key] == v])["miss"]))
            row.append(len({r["person_id"] for r in rows if r[key] == v}))
            body.append(row)
        L += [f"**{name}별**", ""] + table([name] + qids + ["전체", "인원"], body) + [""]

    # 4. 같은 그룹 안 차이
    L += ["## 4. 같은 그룹 안 차이", "",
          "같은 연령대·같은 경로 4명의 답이 모두 같은 그룹의 비율 (12그룹 × 문항). 100%에 가까우면 사람 차이가 답에 반영되지 않은 것입니다.", ""]
    body = []
    for q in qids:
        groups = defaultdict(list)
        for r in rows:
            if r["question_id"] == q:
                groups[(r["age_group"], r["path"])].append(r["answer"])
        same = sum(len(set(a)) == 1 for a in groups.values())
        body.append([q, f"{same} / {len(groups)}", pct(same, len(groups))])
    L += table(["문항", "모두 같은 그룹", "비율"], body) + [""]

    # 5. 원인
    L += ["## 5. 오답·판단 불가의 원인 추정", "",
          "정답 근거 문장 = 아래 표시어가 든 문장. " + ", ".join(f"{q}: {'/'.join(k)}" for q, k in EVIDENCE_KEYS.items()), ""]
    body = []
    for q in qids:
        bad = [r for r in rows if r["question_id"] == q and r["result"] in ("오답", "판단 불가")]
        no_ev = sum(not r["evidence_in_text"] for r in bad)
        unseen = sum(r["evidence_in_text"] and not r["evidence_seen"] for r in bad)
        seen = sum(r["evidence_seen"] for r in bad)
        low = sum(r["knowledge"] == "하" for r in bad)
        body.append([q, len(bad), f"{no_ev} ({pct(no_ev, len(bad))})", f"{unseen} ({pct(unseen, len(bad))})",
                     f"{seen} ({pct(seen, len(bad))})", f"{low} ({pct(low, len(bad))})"])
    L += table(["문항", "오답+판단 불가", "글에 근거 없음", "근거 있었으나 못 봄", "근거를 보고도 틀림", "지식 하"], body)
    L += ["", "- '글에 근거 없음'은 대부분 설계사 화법처럼 받은 글 자체에 정답 근거가 없는 경우입니다.", ""]

    # 6. 재현성
    L += ["## 6. 재현성", "", f"반복 {SETTINGS['repeats']}회 실행 (사용자 결정). 반복이 1회라 재현성은 측정하지 않았습니다.", ""]

    # 7. 품질
    with (DATA / "personas.csv").open(encoding="utf-8-sig") as fh:
        people = list(csv.DictReader(fh))
    regen = sum(bool(p.get("backstory_banned_hits")) for p in people)
    discarded = sum(bool(p.get("backstory_discarded")) for p in people)
    n = len(rows)
    failed = sum(r["status"] != "ok" for r in rows)
    retried = sum(r["tries"] > 1 for r in rows)
    invalid = sum(r["invalid_quote"] for r in rows)
    L += ["## 7. 품질 점검", "",
          f"- JSON 실패(미확인): {failed} / {n} ({pct(failed, n)}), 재요청이 필요했던 응답: {retried}",
          f"- 인용 무효(읽은 글·용어 칸 어디에도 없는 문장을 인용): {invalid} / {n} ({pct(invalid, n)})",
          f"- [용어] 칸의 뜻을 인용한 응답: {sum(r['term_quote'] for r in rows)} / {n} "
          "(읽은 글이 아니라 용어 설명을 근거로 삼음)",
          f"- 배경 이야기 금지 표현 자동 재생성: {regen}명 / 이름이 들어가 사용자 요청으로 재생성: {discarded}명", ""]

    # 8. 비용
    log = [json.loads(l) for l in (RES / "llm_log.jsonl").read_text(encoding="utf-8").splitlines()]
    def cost(entries):
        i, o = sum(e["input_tokens"] for e in entries), sum(e["output_tokens"] for e in entries)
        return len(entries), i, o, i / 1e6 * PRICE_IN + o / 1e6 * PRICE_OUT
    gen = [e for e in log if not e["purpose"].startswith("run")]
    run = [e for e in log if e["purpose"].startswith("run")]
    body = [[name, *[f"{x:,}" for x in cost(es)[:3]], f"${cost(es)[3]:.4f}"]
            for name, es in [("자료 생성(화법·용어·배경)", gen), ("본 실행", run), ("합계", log)]]
    L += ["## 8. 비용", ""] + table(["구분", "호출 수", "입력 토큰", "출력 토큰", "예상 비용"], body)
    L += ["", f"요금 기준: Claude Haiku 5.5 입력 ${PRICE_IN} / 출력 ${PRICE_OUT} (백만 토큰당, 프롬프트 10만 토큰 이하).", ""]

    # 9. 샘플
    L += ["## 9. 샘플 (프롬프트와 응답 전문)", ""]
    picks, used = [], set()
    for result, k in [("정답", 2), ("오답", 2), ("판단 불가", 1)]:
        for r in rows:
            cond = (r["path"], r["question_id"])
            if r["result"] == result and cond not in used and k > 0:
                picks.append(r)
                used.add(cond)
                k -= 1
    for i, r in enumerate(picks, 1):
        L += [f"### 샘플 {i}: {r['result']} · {r['person_id']} · {PATH_NAME[r['path']]} · {r['question_id']} "
              f"(지식 {r['knowledge']}, {DISP_NAME[r['disposition']]}, 꼼꼼함 {r['diligence']})", "",
              "<details><summary>프롬프트</summary>", "", "```", r["prompt"], "```", "", "</details>", "",
              f"- **답**: {r['answer']} (정답 {r['answer_key']}, 확신 {r['confidence']})",
              f"- **이유**: {r['reason']}",
              f"- **인용**: {r['quoted']}" + (" ⚠️ 읽지 않은 문장 인용" if r["invalid_quote"] else ""), ""]

    # 10. 가정값
    L += ["## 10. 가정값과 명세서에서 달라진 점", "",
          "| 항목 | 값 | 비고 |", "|---|---|---|",
          "| 연령대 금융이해력 점수 | 20대 62.6 / 40대 68.4 / 60대 64.7 | 2024 전국민 금융이해력 조사 (사용자 제공) |",
          "| 점수 구간 → 꼼꼼함·지식 비율 | 68↑ 0.65·30/45/25%, 63↑ 0.55·20/45/35%, 63↓ 0.45·15/35/50%, 범위 ±0.15 | 가정 |",
          "| 지식·성향 배정 | **구간 비율대로 인원 배정** (명세서: 확률 추첨) | 48명이라 추첨 치우침이 커서 사용자 결정 |",
          "| 읽기 규칙 | 예산 0.55+0.25×꼼꼼함, 위치 1.0→0.7, 제목 ×1.3, 괄호·※ ×0.5, 보장 ×1.2(낙관 1.4), 예외 ×(0.6+0.4×꼼꼼함)(신중 ×1.2) | 가정. 굵은 글씨 가중은 생략 |",
          "| 문장 종류 판정 | 예외 표시어가 있으면 예외 우선, ※ 25자 이하는 제목 | 구현 결정 |",
          "| 문장 읽기 시드 | 사람 시드 + 문항 + 문장 순번 | 문항 간 같은 순번 문장이 함께 빠지지 않게 |",
          "| 정보 경로 비율 | 5 / 20 / 35 / 40% | 가정 |",
          "| 설계사 화법 | **AI 생성값** (지시문 v2) | v1 은 분쟁 문항 정답을 그대로 말해 폐기 |",
          "| 용어 사전 | '청약철회' 제외, '호르몬 관련 치료제' 하 뜻 1회 재생성 | 정답이 용어 칸으로 새는 것을 막음 |",
          "| 모델 | claude-haiku-5-5 | 사용자 결정 |",
          "| temperature | **보내지 않음** (명세서: 0) | Haiku 5.5 는 temperature 값을 보내면 400 오류 |",
          f"| 생각(thinking) | {SETTINGS['thinking']}, effort {SETTINGS['effort']} | 읽은 글로 바로 답하게 |",
          "| 반복 | **1회** (명세서: 3회) | 사용자 결정 |",
          "| 분쟁 조항 선정 | 일반 지식 기반 분쟁 다발 주제 | 실제 분쟁 사례 미연결 |",
          "| 배경 이야기 다양성 | 48명 중 다수가 수원 거주, 40·60대 남성 교사·철물점 위주 | AI 생성 편중, 판단에는 쓰이지 않음 |", ""]
    return "\n".join(L)


def main() -> int:
    rows = load()
    cols = ["run", "person_id", "question_id", "type", "age_group", "path", "knowledge", "disposition", "diligence",
            "answer_key", "answer", "result", "confidence", "invalid_quote", "read_count", "total",
            "evidence_in_text", "evidence_seen", "status", "tries", "reason", "quoted"]
    with (RES / "scored.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "quoted": " | ".join(r["quoted"])})
    (RES / "report.md").write_text(build_report(rows), encoding="utf-8")
    print(f"{len(rows)}개 채점 → results/scored.csv, results/report.md")
    print(Counter(r["result"] for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
