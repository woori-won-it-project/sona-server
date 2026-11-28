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


# ---------- OpenAI (2026-11-28 추가: Claude 크레딧 소진으로 전환) ----------
# LLM_PROVIDER=openai 이면 call_with_retry 가 OpenAI 로 보낸다. 모델은 OPENAI_MODEL (.env) 또는 settings.yaml openai_model.
# 키는 OPENAI_API_KEY 환경 변수(.env)로만 읽는다.
_oa_client = None
_STOP = {"stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}


def provider() -> str:
    load_dotenv()
    return (os.environ.get("LLM_PROVIDER") or SETTINGS.get("provider") or "anthropic").lower()


def oa_client():
    global _oa_client
    if _oa_client is None:
        load_dotenv()
        import openai
        _oa_client = openai.OpenAI()  # OPENAI_API_KEY 환경 변수 사용
    return _oa_client


def call_openai(prompt: str, purpose: str, json_schema: dict | None = None, extra_log: dict | None = None,
                thinking: str | None = None, effort: str | None = None, max_tokens: int | None = None) -> dict:
    """call_claude 와 같은 모양으로 돌려준다.
    생각 기능: Claude 에서 thinking=disabled 였던 호출(페르소나 읽기·답하기)은 reasoning_effort=none (생각 토큰 0),
    생각을 켰던 호출(보기 만들기 등)은 effort 값(없으면 medium)을 쓴다. gpt-6-luna 는 none/low/medium/high 지원, minimal 미지원."""
    model = os.environ.get("OPENAI_MODEL") or SETTINGS.get("openai_model")
    think = thinking or SETTINGS["thinking"]
    reasoning = "none" if think == "disabled" else {"low": "low", "medium": "medium", "high": "high"}.get(effort or "", "medium")
    params = {
        "model": model,
        "reasoning_effort": reasoning,
        "messages": [{"role": "user", "content": prompt}],
        # 생각(추론) 토큰도 한도에 들어가므로 Claude 때 값의 3배 (최소 4000)
        "max_completion_tokens": max(4000, 3 * (max_tokens or SETTINGS["max_tokens"])),
    }
    if json_schema:
        params["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "output", "schema": json_schema, "strict": True}}
    start = time.perf_counter()
    response = oa_client().chat.completions.create(**params)
    ms = int((time.perf_counter() - start) * 1000)
    choice = response.choices[0]
    stop = _STOP.get(choice.finish_reason, choice.finish_reason)
    if getattr(choice.message, "refusal", None):
        stop = "refusal"
    result = {
        "text": choice.message.content or "",
        "stop_reason": stop,
        "model": response.model,
        "usage": {"input_tokens": response.usage.prompt_tokens, "output_tokens": response.usage.completion_tokens},
        "ms": ms,
        "request_id": getattr(response, "_request_id", None) or response.id,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with _log_lock, LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "time": datetime.now().isoformat(timespec="seconds"), "purpose": purpose,
            "model": response.model, "prompt_sha": prompt_sha(prompt), "stop_reason": stop,
            **result["usage"], "ms": ms, "request_id": result["request_id"], **(extra_log or {}),
        }, ensure_ascii=False) + "\n")
    return result


def call_with_retry(prompt: str, purpose: str, **kw) -> dict:
    """속도 제한·서버 오류는 잠시 쉬었다 다시 보낸다 (SDK 기본 재시도 2회에 더해 최대 3회)."""
    if provider() == "openai":
        return _retry_openai(prompt, purpose, **kw)
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


def _retry_openai(prompt: str, purpose: str, **kw) -> dict:
    import openai
    for attempt in range(4):
        try:
            return call_openai(prompt, purpose, **kw)
        except openai.RateLimitError:
            wait = 20
        except openai.APIStatusError as e:
            if e.status_code < 500:
                raise
            wait = 10
        except openai.APIConnectionError:
            wait = 10
        if attempt == 3:
            raise RuntimeError(f"{purpose}: 재시도 후에도 실패")
        time.sleep(wait)
    raise AssertionError
