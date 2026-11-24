"""case_chunk.embedding 채우기 (OpenAI 임베딩).

대상: embedding 이 NULL 이거나 embedding_model 이 지금 모델과 다른 청크. --force 면 전부.
묶음(기본 100개) 단위로 요청하고 묶음마다 커밋하므로, 중간에 멈춰도 다시 실행하면 남은 것만 처리한다.
429·5xx·네트워크 오류는 지수 백오프로 최대 3번 재시도, 그래도 실패하면 그 묶음만 건너뛰고 기록한다.
인증 실패·크레딧 부족(insufficient_quota)은 이후 묶음도 모두 실패하므로 즉시 중단한다.
끝나면 ANALYZE case_chunk.

사용 (레포 루트에서):
    python scripts/collector/embedder.py --dry-run
    python scripts/collector/embedder.py
    python scripts/collector/embedder.py --force

옵션:
    --model        임베딩 모델 (기본 text-embedding-3-small)
    --dimensions   차원 (기본 1536). case_chunk.embedding 컬럼 차원과 같아야 한다
    --batch-size   한 요청에 묶는 청크 수 (기본 100)
    --force        이미 임베딩된 청크도 다시 임베딩
    --dry-run      API 호출 없이 대상 청크 수, 예상 토큰 수, 예상 비용(USD)만 출력

설정:
    OPENAI_API_KEY  루트 .env 값을 OS 환경 변수보다 우선. 키 값은 어디에도 출력하지 않는다
    POSTGRES_*      collector.py 와 같은 방식
"""
import argparse
import os
import random
import re
import sys
import time

from collector import ROOT, connect, load_env

DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_DIMENSIONS = 1536
PRICE_PER_1M_TOKENS = {  # USD, OpenAI 공개 단가
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}
MAX_RETRIES = 3
BACKOFF_BASE = 2.0  # 2, 4, 8초 (+지터)


# ---------------------------------------------------------------- 설정

def openai_key() -> str | None:
    """루트 .env 의 OPENAI_API_KEY 를 OS 환경 변수보다 우선."""
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*OPENAI_API_KEY\s*=\s*(.*)$", line)
            if m and m.group(1).strip().strip('"').strip("'"):
                return m.group(1).strip().strip('"').strip("'")
    return os.environ.get("OPENAI_API_KEY") or None


def masker(key: str | None):
    def mask(text: str | None) -> str | None:
        if not text:
            return text
        if key:
            text = text.replace(key, "***")
        return re.sub(r"sk-[A-Za-z0-9_\-*.]+", "***", text)
    return mask


def column_dimensions(conn) -> int | None:
    row = conn.execute("""
        SELECT format_type(atttypid, atttypmod) FROM pg_attribute
        WHERE attrelid = 'case_chunk'::regclass AND attname = 'embedding'""").fetchone()
    m = re.match(r"vector\((\d+)\)", row[0]) if row else None
    return int(m.group(1)) if m else None


def cost(tokens: int, model: str) -> float | None:
    price = PRICE_PER_1M_TOKENS.get(model)
    return round(tokens / 1_000_000 * price, 6) if price is not None else None


# ---------------------------------------------------------------- 대상

def load_targets(conn, model: str, force: bool) -> list[tuple[int, str, str]]:
    where = "" if force else "WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %(model)s"
    return conn.execute(f"SELECT id, content, content_hash FROM case_chunk {where} ORDER BY id",
                        {"model": model}).fetchall()


def count_tokens(texts: list[str], model: str) -> int:
    import tiktoken
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return sum(len(enc.encode(t)) for t in texts)


# ---------------------------------------------------------------- 호출

class FatalAPIError(Exception):
    """이후 묶음도 성공할 수 없는 오류 (인증 실패, 크레딧 부족 등)."""


def error_info(e, mask) -> dict:
    import openai
    info = {"error": type(e).__name__}
    if isinstance(e, openai.APIStatusError):
        body = e.body.get("error", e.body) if isinstance(e.body, dict) else {}
        body = body if isinstance(body, dict) else {}
        info.update(http_status=e.status_code, code=body.get("code"), type=body.get("type"),
                    message=mask(body.get("message") or str(e)))
    return info


def embed_batch(client, texts: list[str], model: str, dimensions: int, mask):
    """재시도 포함 한 묶음 요청. 반환: (벡터 목록, 사용 토큰)."""
    import openai
    kwargs = {"model": model, "input": texts}
    if model.startswith("text-embedding-3"):
        kwargs["dimensions"] = dimensions
    attempt = 0
    while True:
        try:
            res = client.embeddings.create(**kwargs)
            vectors = [d.embedding for d in sorted(res.data, key=lambda d: d.index)]
            return vectors, res.usage.total_tokens
        except openai.AuthenticationError as e:
            raise FatalAPIError(error_info(e, mask)) from None
        except openai.RateLimitError as e:
            info = error_info(e, mask)
            if info.get("code") == "insufficient_quota":
                raise FatalAPIError(info) from None
            retryable = True
        except openai.APIStatusError as e:
            if e.status_code in (401, 403):
                raise FatalAPIError(error_info(e, mask)) from None
            retryable = e.status_code >= 500
            info = error_info(e, mask)
        except (openai.APIConnectionError, openai.APITimeoutError) as e:
            retryable, info = True, error_info(e, mask)
        if not retryable or attempt >= MAX_RETRIES:
            info["attempts"] = attempt + 1
            raise RuntimeError(info)
        attempt += 1
        wait = BACKOFF_BASE ** attempt + random.uniform(0, 1)
        print(f"  재시도 {attempt}/{MAX_RETRIES} ({info.get('http_status') or info['error']}), {wait:.1f}초 대기")
        time.sleep(wait)


def to_vector_literal(v: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


# ---------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description="case_chunk 임베딩")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dimensions", type=int, default=DEFAULT_DIMENSIONS)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 2048:
        raise SystemExit("--batch-size 는 1~2048")

    conn = connect(load_env())
    col_dim = column_dimensions(conn)
    if col_dim != args.dimensions:
        raise SystemExit(f"--dimensions {args.dimensions} 가 case_chunk.embedding 컬럼 차원({col_dim})과 다릅니다")

    targets = load_targets(conn, args.model, args.force)
    print(f"model={args.model} dimensions={args.dimensions} force={args.force} 대상 청크={len(targets)}")

    if args.dry_run:
        tokens = count_tokens([t[1] for t in targets], args.model)
        est = cost(tokens, args.model)
        print(f"예상 토큰={tokens:,} 예상 비용=${est:.6f}" if est is not None
              else f"예상 토큰={tokens:,} 예상 비용=(단가 미등록 모델)")
        conn.close()
        return

    if not targets:
        print("임베딩할 청크 없음")
        conn.execute("ANALYZE case_chunk")
        conn.close()
        return

    key = openai_key()
    if not key:
        raise SystemExit("OPENAI_API_KEY 가 .env 와 환경 변수에 없습니다")
    import openai
    client = openai.OpenAI(api_key=key, max_retries=0, timeout=60)
    mask = masker(key)

    started = time.monotonic()
    done = failed = tokens = 0
    failures = []
    batches = [targets[i:i + args.batch_size] for i in range(0, len(targets), args.batch_size)]
    for n, batch in enumerate(batches, 1):
        ids = [t[0] for t in batch]
        try:
            vectors, used = embed_batch(client, [t[1] for t in batch], args.model, args.dimensions, mask)
        except FatalAPIError as e:
            print(f"[{n}/{len(batches)}] 중단: {e.args[0]}", file=sys.stderr)
            failed += sum(len(b) for b in batches[n - 1:])
            failures.append({"batch": n, "chunk_ids": f"{ids[0]}..{ids[-1]}", **e.args[0]})
            break
        except RuntimeError as e:
            print(f"[{n}/{len(batches)}] 건너뜀: {e.args[0]}", file=sys.stderr)
            failed += len(batch)
            failures.append({"batch": n, "chunk_ids": f"{ids[0]}..{ids[-1]}", **e.args[0]})
            continue
        if len(vectors) != len(batch) or any(len(v) != args.dimensions for v in vectors):
            print(f"[{n}/{len(batches)}] 건너뜀: 응답 개수/차원 불일치", file=sys.stderr)
            failed += len(batch)
            failures.append({"batch": n, "chunk_ids": f"{ids[0]}..{ids[-1]}", "error": "응답 개수/차원 불일치"})
            continue
        with conn.transaction():  # 묶음 단위 커밋
            with conn.cursor() as cur:
                # content_hash 조건: 조회 후 청크 내용이 바뀌었으면 옛 내용의 벡터를 쓰지 않는다
                cur.executemany(
                    "UPDATE case_chunk SET embedding = %s::vector, embedding_model = %s, updated_at = now() "
                    "WHERE id = %s AND content_hash = %s",
                    [(to_vector_literal(v), args.model, cid, h) for (cid, _, h), v in zip(batch, vectors)])
        done += len(batch)
        tokens += used
        print(f"[{n}/{len(batches)}] {len(batch)}개 저장, 토큰 {used:,}")

    conn.execute("ANALYZE case_chunk")
    conn.close()
    elapsed = time.monotonic() - started
    est = cost(tokens, args.model)
    print(f"완료: 처리={done} 실패={failed} 토큰={tokens:,} "
          f"비용=${est:.6f} 소요={elapsed:.1f}초" if est is not None else
          f"완료: 처리={done} 실패={failed} 토큰={tokens:,} 소요={elapsed:.1f}초")
    for f in failures:
        print(f"  실패 묶음: {f}", file=sys.stderr)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
