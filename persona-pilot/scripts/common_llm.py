"""Claude 호출 한 곳. 02b(생성)와 05(실행)가 함께 쓴다.

- API 키는 환경 변수 ANTHROPIC_API_KEY 로만 읽는다 (SDK 가 자동으로 읽음). 코드·결과 파일에 남기지 않는다.
- 호출마다 results/llm_log.jsonl 에 모델, 프롬프트 해시, 토큰 수, 걸린 시간을 남긴다.
"""

import hashlib
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import anthropic
import yaml

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "results" / "llm_log.jsonl"
SETTINGS = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))

_client = None
_log_lock = threading.Lock()


def load_dotenv() -> None:
    """persona-pilot/.env 에 ANTHROPIC_API_KEY=... 가 있으면 환경 변수로 올린다.

    .env 는 레포 .gitignore 에 들어 있어 커밋되지 않는다. 이미 환경 변수가 있으면 그것을 쓴다.
    """
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        load_dotenv()
        _client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경 변수 사용
    return _client


def prompt_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def call_claude(prompt: str, purpose: str, json_schema: dict | None = None, extra_log: dict | None = None,
                thinking: str | None = None, effort: str | None = None, max_tokens: int | None = None) -> dict:
    """프롬프트 하나를 보내고 {"text", "stop_reason", "usage", "ms", "model"} 를 돌려준다.

    json_schema 를 주면 structured outputs 로 그 모양의 JSON 만 받는다.
    thinking·effort·max_tokens 를 주면 이 호출만 settings.yaml 값 대신 그 값을 쓴다 (B안 문항 생성·채점용).
    거절(refusal)·길이 초과도 예외 없이 stop_reason 으로 돌려주고, 판단은 호출한 쪽이 한다.
    """
    params = {
        "model": SETTINGS["model"],
        "max_tokens": max_tokens or SETTINGS["max_tokens"],
        "messages": [{"role": "user", "content": prompt}],
        "thinking": {"type": thinking or SETTINGS["thinking"]},
        "output_config": {"effort": effort or SETTINGS["effort"]},
    }
    if json_schema:
        params["output_config"]["format"] = {"type": "json_schema", "schema": json_schema}

    start = time.perf_counter()
    response = client().messages.create(**params)
    ms = int((time.perf_counter() - start) * 1000)

    text = "".join(b.text for b in response.content if b.type == "text")
    result = {
        "text": text,
        "stop_reason": response.stop_reason,
        "model": response.model,
        "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        "ms": ms,
        "request_id": response._request_id,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with _log_lock, LOG.open("a", encoding="utf-8") as f:  # 05 가 여러 스레드로 부르므로 한 줄씩 잠가 쓴다
        f.write(json.dumps({
            "time": datetime.now().isoformat(timespec="seconds"), "purpose": purpose,
            "model": response.model, "prompt_sha": prompt_sha(prompt), "stop_reason": response.stop_reason,
            **result["usage"], "ms": ms, "request_id": result["request_id"], **(extra_log or {}),
        }, ensure_ascii=False) + "\n")
    return result


def call_with_retry(prompt: str, purpose: str, **kw) -> dict:
    """속도 제한·서버 오류는 잠시 쉬었다 다시 보낸다 (SDK 기본 재시도 2회에 더해 최대 3회)."""
    for attempt in range(4):
        try:
            return call_claude(prompt, purpose, **kw)
        except anthropic.RateLimitError as e:
            wait = int(e.response.headers.get("retry-after", "20"))
        except anthropic.APIStatusError as e:
            if e.status_code < 500:
                raise  # 400·401 등은 다시 보내도 같으므로 바로 알린다
            wait = 10
        except anthropic.APIConnectionError:
            wait = 10
        if attempt == 3:
            raise RuntimeError(f"{purpose}: 재시도 후에도 실패")
        time.sleep(wait)
    raise AssertionError
