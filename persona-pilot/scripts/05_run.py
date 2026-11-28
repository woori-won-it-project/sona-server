"""4-9. 본 실행: 조립된 프롬프트 192개를 Claude 에 보내고 답을 저장한다.

실행: python scripts/05_run.py            (persona-pilot 폴더에서, C6 승인 후)
결과: results/responses/run1.jsonl  (중간에 멈춰도 다시 실행하면 끝난 것은 건너뛴다)

- 답은 structured outputs 로 {"answer","reason","quoted","confidence"} 모양만 받는다.
- 그래도 JSON 이 아니거나 모양이 틀리면 최대 2회(settings.json_retry) 다시 요청, 그래도 실패면 failed.
- 거절(refusal)·길이 초과도 failed 로 기록한다.
"""

import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_llm import SETTINGS, call_with_retry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "results" / "prompts" / "prompts.jsonl"
OUT_DIR = ROOT / "results" / "responses"

# 04 의 응답 모양(ANSWER_SCHEMA)을 그대로 쓴다 (파일 이름이 숫자로 시작해 import 문을 못 씀)
_spec = importlib.util.spec_from_file_location("build_prompts", Path(__file__).parent / "04_build_prompts.py")
_bp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bp)
SCHEMA = _bp.ANSWER_SCHEMA
ANSWERS = set(SCHEMA["properties"]["answer"]["enum"])
WORKERS = 4  # 동시에 보내는 요청 수


def parse(text: str) -> dict | None:
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        return None
    ok = (isinstance(d, dict) and d.get("answer") in ANSWERS and isinstance(d.get("reason"), str)
          and isinstance(d.get("quoted"), list) and d.get("confidence") in {1, 2, 3, 4, 5})
    return d if ok else None


def run_one(item: dict, run_no: int) -> dict:
    purpose = f"run{run_no}:{item['person_id']}:{item['question_id']}"
    tries, last, usage_in, usage_out, ms = 0, None, 0, 0, 0
    status, parsed = "failed", None
    for _ in range(1 + SETTINGS["json_retry"]):
        tries += 1
        r = call_with_retry(item["prompt"], purpose, json_schema=SCHEMA)
        last = r
        usage_in += r["usage"]["input_tokens"]
        usage_out += r["usage"]["output_tokens"]
        ms += r["ms"]
        if r["stop_reason"] == "refusal":
            break  # 같은 프롬프트로는 다시 보내도 거절되므로 바로 failed
        if r["stop_reason"] == "end_turn":
            parsed = parse(r["text"])
            if parsed:
                status = "ok"
                break
    return {
        "run": run_no, "person_id": item["person_id"], "question_id": item["question_id"],
        "status": status, "stop_reason": last["stop_reason"],
        "answer": parsed["answer"] if parsed else None,
        "reason": parsed["reason"] if parsed else None,
        "quoted": parsed["quoted"] if parsed else [],
        "confidence": parsed["confidence"] if parsed else None,
        "raw": last["text"], "tries": tries, "model": last["model"],
        "input_tokens": usage_in, "output_tokens": usage_out, "ms": ms, "prompt_sha": item["prompt_sha"],
    }


def main() -> int:
    items = [json.loads(l) for l in PROMPTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    not_ready = sorted({m for it in items for m in it["missing"]})
    if not_ready:
        raise SystemExit(f"프롬프트에 아직 생성되지 않은 자료가 있습니다: {not_ready}. 04 를 --draft 없이 다시 실행하세요.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lock = Lock()
    for run_no in range(1, SETTINGS["repeats"] + 1):
        out = OUT_DIR / f"run{run_no}.jsonl"
        done = set()
        if out.exists():
            done = {(d["person_id"], d["question_id"]) for d in map(json.loads, out.read_text(encoding="utf-8").splitlines())}
        todo = [it for it in items if (it["person_id"], it["question_id"]) not in done]
        print(f"run{run_no}: {len(todo)}개 남음 (완료 {len(done)})")

        with ThreadPoolExecutor(WORKERS) as pool, out.open("a", encoding="utf-8") as f:
            futures = [pool.submit(run_one, it, run_no) for it in todo]
            for n, fut in enumerate(as_completed(futures), 1):
                row = fut.result()
                with lock:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                if n % 24 == 0 or n == len(todo):
                    print(f"  {n}/{len(todo)}", flush=True)

        rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        failed = sum(r["status"] != "ok" for r in rows)
        print(f"run{run_no} 끝: {len(rows)}개, 실패 {failed}개, 재요청 {sum(r['tries'] - 1 for r in rows)}회")
    return 0


if __name__ == "__main__":
    sys.exit(main())
