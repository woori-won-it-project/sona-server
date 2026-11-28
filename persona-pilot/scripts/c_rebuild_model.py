"""모델을 바꾼 뒤 보기를 그 모델 기준으로 다시 만든다 (2026-11-28, gpt-6-luna 전환).
찍기 검사(읽지 않고 30회 선택)에서 40% 를 넘는 문항만 다시 만들고(최대 rounds 회), 마지막 찍기 결과를 guess.json 에 저장한다.
실행: python scripts/c_rebuild_model.py dy   또는   python scripts/c_rebuild_model.py won
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


case = sys.argv[1]
rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 2
sys.argv = sys.argv[:1]
if case == "won":
    v = load("c_validate", "c_validate.py")
    v.setup("won")
    t = v.t
    out = Path(t.OUT)
else:
    t = load("c_tune", "c_tune.py")
    out = Path(t.OUT)
t.bm.STRONG["effort"] = "medium"

rates = t.guess_rates(30)
print("[시작] 찍기:", {k: f"{x:.0%}" for k, x in rates.items()}, flush=True)
for r in range(rounds):
    bad = [k for k, x in rates.items() if x > 0.4]
    if not bad:
        break
    fb = "\n[이전 보기에서 읽지 않은 사람이 보기 문장만 보고 정답을 알아챈 문항]\n" + "\n".join(
        f"- {k}: {rates[k]:.0%}가 정답을 고름. 이전 보기: "
        + " / ".join(o["text"] + ("(정답)" if o["correct"] else "") for o in t.OPTS[k]) for k in bad) + \
        "\n세 보기를 완전히 새로 쓰세요. 정답만 상식에 맞는 보기가 되지 않게, 오답 두 개도 보험을 아는 사람에게 똑같이 그럴듯하게 쓰세요.\n"
    for i in range(0, len(bad), 4):
        t.stage_options(only=bad[i:i + 4], feedback=fb)
    new = t.guess_rates(30)
    # 다시 만든 문항이 더 나빠졌으면 이전 보기로 되돌린다
    rates = {k: (new[k] if k in bad else rates[k]) for k in rates}
    print(f"[{r + 1}회차] 찍기:", {k: f"{x:.0%}" for k, x in rates.items()}, flush=True)
(out / "guess.json").write_text(json.dumps(rates, ensure_ascii=False, indent=1), encoding="utf-8")
print("상식 문항(60% 초과):", sorted(k for k, x in rates.items() if x > 0.6),
      "| 평균(상식 제외):", f"{sum(x for x in rates.values() if x <= 0.6) / max(1, sum(1 for x in rates.values() if x <= 0.6)):.0%}")
