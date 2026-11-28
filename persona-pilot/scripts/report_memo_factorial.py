"""Summarize saved trials without calling an API."""
import json
from pathlib import Path

out = Path(__file__).resolve().parents[1] / "results_valid/dy_rag/memo_factorial_1"
rows = [json.loads(p.read_text(encoding="utf8")) for p in sorted(out.glob("*.json"))]
assert len(rows) == 78
items = list(rows[0]["correct"])
lines = ["# Luna 메모 실험 · 동양생명 RAG", "",
         "동일 설명서·300자 메모, 3개 용어 친숙도 × 재확인 여부 × 감액 안내 원문/수정 × 보기 순서 6회. 빈 메모 6회. 각 행은 맞힌 횟수.",
         "기간 표현은 메모에 ‘내내’가 문자 그대로 등장한 건수로, 의미 채점과 다르다.", "",
         "|조건|횟수|"+"|".join(items)+"|‘내내’ 메모|","|---|---:|"+"---:|"*(len(items)+1)]
def add(label, group):
    counts = [sum(r["correct"][k] for r in group) for k in items]
    lines.append("|"+"|".join(map(str,[label,len(group),*counts,sum("내내" in r["memo"] for r in group)]))+"|")
add("빈 메모", [r for r in rows if r["level"]=="empty"])
for v in ["orig","edit"]:
    group = [r for r in rows if r["version"]==v]
    add(v,group)
    for key, values in [("level",["high","mid","low"]),("check",[0,1])]:
        for val in values:
            add(f"{v} {key}={val}",[r for r in group if r[key]==val])
for key,values in [("level",["high","mid","low"]),("check",[0,1])]:
    for val in values:
        add(f"합산 {key}={val}",[r for r in rows if r["level"]!="empty" and r[key]==val])
(out/"report.md").write_text("\n".join(lines)+"\n", encoding="utf8")
