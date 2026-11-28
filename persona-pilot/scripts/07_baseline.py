"""기준값: 아무것도 읽지 않은 상태(배경·성향·읽은 글·용어 없이 질문만)에서 AI 가 어떻게 답하는지 잰다.

AI 가 원래 기우는 쪽을 알아야, 가상고객의 답이 '읽은 글 때문'인지 'AI 의 기본 성향 때문'인지 가를 수 있다.
temperature 를 보낼 수 없어(Haiku 5.5) 같은 질문도 답이 달라질 수 있으므로 문항마다 N 번 묻는다.

실행: python scripts/07_baseline.py [--n 10]   (persona-pilot 폴더에서)
결과: results/baseline.jsonl
"""

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_llm import call_with_retry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "baseline.jsonl"

# 04 와 같은 답 지시문·응답 모양을 쓴다
_spec = importlib.util.spec_from_file_location("build_prompts", Path(__file__).parent / "04_build_prompts.py")
_bp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bp)

TEMPLATE = """[상황]
{question}

{instruction}"""


def ask(q: dict, n: int) -> dict:
    prompt = TEMPLATE.format(question=q["question"], instruction=_bp.INSTRUCTION)
    r = call_with_retry(prompt, f"baseline:{q['question_id']}:{n}", json_schema=_bp.ANSWER_SCHEMA)
    try:
        d = json.loads(r["text"])
    except json.JSONDecodeError:
        d = {}
    return {"question_id": q["question_id"], "n": n, "answer": d.get("answer"), "reason": d.get("reason"),
            "confidence": d.get("confidence"), "answer_key": q["answer_key"],
            "question_sha": hashlib.sha256(q["question"].encode()).hexdigest()[:12]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="문항마다 묻는 횟수")
    ap.add_argument("--questions", default="data/questions.json", help="질문 파일 (초안 시험용)")
    ap.add_argument("--out", default=str(OUT.relative_to(ROOT)), help="결과 파일")
    args = ap.parse_args()
    questions = json.loads((ROOT / args.questions).read_text(encoding="utf-8"))
    out = ROOT / args.out
    jobs = [(q, i) for q in questions for i in range(1, args.n + 1)]
    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(lambda job: ask(*job), jobs))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    for q in questions:
        c = Counter(r["answer"] for r in rows if r["question_id"] == q["question_id"])
        print(f"{q['question_id']} (정답 {q['answer_key']}): {dict(c)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
