"""개념 태그 (약관 용어 기준): 개념 목록 → 자료 태그(case_tag CONCEPT/LLM) → 조항(질의) 개념.

단계 (모두 OpenAI chat completions, temperature 0, JSON 응답. 결과는 캐시해서 입력·모델·프롬프트가 같으면 다시 부르지 않음)
    vocab  category='보험' 인 CASE·STANDARD·DECISION(각하 제외)의 제목 + dispute_issue 로 반복 개념 40~80개
           (이름·한 줄 정의·같은 뜻으로 쓰이는 말) → data/raw/_gold/concept_vocab.json
           정답표·gold_queries 는 보지 않는다
    tag    같은 자료마다 (제목 + dispute_issue + decision_reason 앞 1500자) 목록 중 0~3개 + confidence
           STANDARD 는 dispute_issue·decision_reason 이 비어 있어 요지(summary) 앞 1500자를 대신 쓴다
           → case_tag (axis='CONCEPT', source='LLM') 를 지우고 다시 넣음. PRODUCT 태그는 건드리지 않음
           목록에 없는 이름은 버리고 기록. 캐시 data/raw/_gold/concept_tag_cache.json
    query  gold_queries.json 의 query_text 마다 같은 목록에서 0~3개 (정답·hint_cases·clause_ref 는 넣지 않음)
           → data/raw/_gold/query_concepts.json
    호출 수·토큰·비용은 data/raw/_report/concept_llm_usage.json 에 단계별로 누적

모델: 환경 변수 LLM_MODEL, 없으면 이 키로 쓸 수 있는 'gpt-<버전>-mini' 중 최신 (retrieval_eval.resolve_llm_model)

사용 (레포 루트에서):
    python scripts/collector/concept_tags.py all        # vocab → tag → query
    python scripts/collector/concept_tags.py tag --dry-run
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone

from collector import RAW_DIR, connect, load_env
from embedder import masker, openai_key
from retrieval_eval import LLM_PRICES, QUERIES_FILE, case_key, resolve_llm_model

GOLD_DIR = RAW_DIR / "_gold"
VOCAB_FILE = GOLD_DIR / "concept_vocab.json"
TAG_CACHE = GOLD_DIR / "concept_tag_cache.json"
QUERY_FILE = GOLD_DIR / "query_concepts.json"
USAGE_FILE = RAW_DIR / "_report" / "concept_llm_usage.json"

PROMPT_VERSION = "v2"  # v1: 개념 수 초과 시 합치기 지시가 너무 넓어 치료 개념이 사라짐 (91→43)
VOCAB_MIN, VOCAB_MAX = 40, 80
MAX_TAGS = 3
TEXT_MAX = 1500
ISSUE_MAX = 200          # 개념 목록 입력: dispute_issue 앞부분만
TAG_BATCH = 8            # 자료 태그: 한 호출에 묶는 자료 수
QUERY_BATCH = 11

SYSTEM = "너는 한국 보험 약관과 금융감독원 분쟁조정 사례에 익숙한 보험 분쟁 전문가다. 요청한 JSON 만 출력한다."

VOCAB_PROMPT = """아래는 금융감독원 보험 분쟁조정 자료(분쟁사례·분쟁해결기준·분쟁조정결정례) {n}건의 제목과 쟁점이다.
이 자료들에서 반복해서 다투어지는 '개념'을 보험 약관 용어 기준으로 {vmin}~{vmax}개 뽑아라.

- name: 약관에 쓰이는 용어 기준의 개념 이름 (예: 근골격계 이학요법, 비급여 주사료, 체외충격파, 시력교정술, 본인부담금 상한제,
  계약 전 알릴 의무, 부담보, 수술의 정의). 짧은 명사구
- definition: 한 줄 정의 (약관에서 무엇을 정하는지)
- synonyms: 분쟁 자료·현장에서 같은 뜻으로 쓰이는 말 3~10개 (동의어, 구체적인 치료·시술·상품·행위 이름 포함. 예: 도수치료, 증식치료, FIMS)
- '보험금 지급', '약관 해석' 처럼 거의 모든 자료에 해당하는 너무 넓은 개념은 빼라
- 개념끼리 겹치지 않게 하고, 여러 자료에서 반복되는 것만 넣어라
- 특정 회사·사람·사건 번호는 넣지 마라

JSON 으로만 답하라: {{"concepts": [{{"name": "...", "definition": "...", "synonyms": ["..."]}}]}}

[자료]
{items}"""

PICK_PROMPT = """아래 [개념 목록] 중에서 각 {what}의 핵심 쟁점에 해당하는 개념을 0~3개 골라라.

- 반드시 목록의 name 을 글자 그대로 써라. 목록에 없는 개념은 만들지 마라
- 해당하는 개념이 없으면 빈 목록
- confidence: 0~1 (그 개념이 이 {what}의 핵심 쟁점이라고 확신하는 정도)
- 모든 id 에 대해 답하라

JSON 으로만 답하라: {{"results": [{{"id": "...", "concepts": [{{"name": "...", "confidence": 0.0}}]}}]}}

[개념 목록]
{vocab}

[{what}]
{items}"""


# ---------------------------------------------------------------- 공통

class LLM:
    def __init__(self):
        import openai
        key = openai_key()
        if not key:
            raise SystemExit("OPENAI_API_KEY 가 .env 와 환경 변수에 없습니다")
        self.key, self.mask = key, masker(key)
        self.client = openai.OpenAI(api_key=key, max_retries=3, timeout=300)
        self.model, self.model_source = resolve_llm_model(self.client)
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "resolved_models": set()}

    def ask(self, prompt: str) -> dict:
        import openai
        try:
            res = self.client.chat.completions.create(
                model=self.model, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
        except openai.APIError as e:
            raise SystemExit(self.mask(f"API 실패: {type(e).__name__} {getattr(e, 'status_code', '')}")) from None
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += res.usage.prompt_tokens
        self.usage["completion_tokens"] += res.usage.completion_tokens
        self.usage["resolved_models"].add(res.model)
        return json.loads(res.choices[0].message.content)

    def record(self, stage: str) -> dict:
        price = LLM_PRICES.get(self.model)
        u = dict(self.usage, resolved_models=sorted(self.usage["resolved_models"]), model=self.model,
                 model_source=self.model_source, price_per_1m=list(price) if price else None,
                 cost_usd=round(self.usage["prompt_tokens"] / 1e6 * price[0]
                                + self.usage["completion_tokens"] / 1e6 * price[1], 6) if price else None,
                 at=datetime.now(timezone.utc).isoformat())
        data = json.loads(USAGE_FILE.read_text(encoding="utf-8")) if USAGE_FILE.exists() else {"runs": []}
        data["runs"].append({"stage": stage, **u})
        text = json.dumps(data, ensure_ascii=False, indent=2)
        assert self.key not in text
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        USAGE_FILE.write_text(text, encoding="utf-8")
        return u


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def load_docs(conn) -> list[dict]:
    """category='보험', 각하 제외 자료. 개념 목록·태그 입력."""
    cur = conn.execute("""
        SELECT id, doc_kind, source_key, title, dispute_issue, decision_reason, summary
        FROM dispute_case WHERE category = '보험' AND coalesce(meta->>'disposition', '') <> '각하'
        ORDER BY doc_kind, split_part(source_key, '-', 1)::int, source_key""")
    docs = []
    for cid, kind, key, title, issue, reason, summary in cur.fetchall():
        body = reason if reason else (summary if kind == "STANDARD" else None)  # STANDARD 는 요지로 대신
        docs.append({"id": cid, "key": case_key(kind, key), "doc_kind": kind, "title": (title or "").strip(),
                     "issue": (issue or "").strip(), "body": (body or "").strip()[:TEXT_MAX],
                     "body_source": "decision_reason" if reason else ("summary(요지)" if body else None)})
    return docs


def vocab_text(vocab: list[dict]) -> str:
    return "\n".join(f"- {c['name']}: {c['definition']} (같은 말: {', '.join(c['synonyms'])})" for c in vocab)


def oneline(s: str) -> str:
    return " ".join(s.split())


# ---------------------------------------------------------------- 1. 개념 목록

def clean_concepts(data: dict) -> list[dict]:
    concepts, names = [], set()
    for c in data.get("concepts", []):
        name = str(c.get("name", "")).strip()
        if not name or name in names:
            continue
        names.add(name)
        concepts.append({"name": name, "definition": str(c.get("definition", "")).strip(),
                         "synonyms": [str(s).strip() for s in c.get("synonyms", []) if str(s).strip()][:10]})
    return concepts


SUPPLEMENT_VERSION = "s1"
SUPPLEMENT_PROMPT = """아래 [개념 목록]은 [자료]에서 뽑은 보험 분쟁 개념 {n}개다. 목록에 빠진 개념만 찾아라.

- [자료]의 여러 건에서 반복되는데 목록의 어느 개념에도 들어 있지 않은 것만 (특히 제목에 나오는 구체적인 치료·시술·검사·상품 이름)
- 이미 목록에 있는 개념과 뜻이 같거나 그 개념에 포함되면 넣지 마라
- 최대 {room}개. 빠진 것이 없으면 빈 목록
- 형식은 목록과 같다 (name 은 약관 용어 기준, definition 한 줄, synonyms 3~10개)

JSON 으로만 답하라: {{"concepts": [{{"name": "...", "definition": "...", "synonyms": ["..."]}}]}}

[개념 목록]
{vocab}

[자료]
{items}"""


def supplement_vocab(llm: LLM, vocab: dict, lines: list[str]) -> dict:
    """보완 1회: 같은 자료를 다시 주고 목록에 빠진 반복 개념만 받아 덧붙인다 (총 VOCAB_MAX 이하). 기존 개념은 그대로."""
    concepts = vocab["concepts"]
    room = VOCAB_MAX - len(concepts)
    added = []
    if room > 0:
        names = {c["name"] for c in concepts}
        got = clean_concepts(llm.ask(SUPPLEMENT_PROMPT.format(
            n=len(concepts), room=room, vocab=vocab_text(concepts), items="\n".join(lines))))
        added = [c for c in got if c["name"] not in names][:room]
    vocab.update(concepts=concepts + added, count=len(concepts) + len(added), supplement_version=SUPPLEMENT_VERSION,
                 supplement={"added": [c["name"] for c in added], "base_count": len(concepts),
                             "prompt": SUPPLEMENT_PROMPT, "at": datetime.now(timezone.utc).isoformat()})
    VOCAB_FILE.write_text(json.dumps(vocab, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"vocab 보완: +{len(added)}개 → {vocab['count']}개 {[c['name'] for c in added]}")
    return vocab


def build_vocab(llm: LLM, docs: list[dict]) -> dict:
    seen, lines = set(), []
    for d in docs:
        line = oneline(d["title"]) + (f" / 쟁점: {oneline(d['issue'])[:ISSUE_MAX]}"
                                      if d["issue"] and oneline(d["issue"]) != oneline(d["title"]) else "")
        if line not in seen:
            seen.add(line)
            lines.append(f"- {line}")
    prompt = VOCAB_PROMPT.format(n=len(lines), vmin=VOCAB_MIN, vmax=VOCAB_MAX, items="\n".join(lines))
    input_hash = sha([prompt, llm.model, PROMPT_VERSION])
    if VOCAB_FILE.exists():
        old = json.loads(VOCAB_FILE.read_text(encoding="utf-8"))
        if old.get("input_hash") == input_hash:
            if old.get("supplement_version") != SUPPLEMENT_VERSION:
                return supplement_vocab(llm, old, lines)
            print(f"vocab: 캐시 사용 ({len(old['concepts'])}개)")
            return old
    concepts = clean_concepts(llm.ask(prompt))
    attempts = [len(concepts)]
    if not VOCAB_MIN <= len(concepts) <= VOCAB_MAX:  # 한 번만 고쳐 달라고 한다 (합치기 / 늘리기)
        fix = (f"아래 개념 목록은 {len(concepts)}개다. "
               + (f"{VOCAB_MAX - 10}~{VOCAB_MAX}개로 줄여라. 뜻이 거의 같은 개념끼리만 합치거나, 자료 1~2건에만 나오는 개념을 빼라. "
                  "구체적인 치료·시술·검사 개념(예: 근골격계 이학요법, 비급여 주사료, 체외충격파, 시력교정술)을 "
                  "'실손의료비' 같은 넓은 개념에 합치지 마라. " if len(concepts) > VOCAB_MAX
                  else f"자료에서 반복되는 개념을 더해 {VOCAB_MIN}개 이상으로 늘려라. ")
               + "합칠 때는 synonyms 도 합쳐라. 같은 JSON 형식으로만 답하라.\n\n"
               + json.dumps({"concepts": concepts}, ensure_ascii=False))
        concepts = clean_concepts(llm.ask(fix))
        attempts.append(len(concepts))
    if not VOCAB_MIN <= len(concepts) <= VOCAB_MAX:
        raise SystemExit(f"개념 수 {attempts} 가 {VOCAB_MIN}~{VOCAB_MAX} 밖입니다 (저장 안 함)")
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "model": llm.model, "temperature": 0,
           "prompt_version": PROMPT_VERSION, "input_hash": input_hash,
           "input": {"documents": len(docs), "unique_lines": len(lines),
                     "by_doc_kind": {k: sum(1 for d in docs if d["doc_kind"] == k) for k in ("CASE", "STANDARD", "DECISION")},
                     "fields": "제목 + dispute_issue(앞 200자, 제목과 같으면 생략)", "category": "보험", "excluded": "각하"},
           "prompt": {"system": SYSTEM, "user_template": VOCAB_PROMPT},
           "count_by_attempt": attempts, "count": len(concepts), "concepts": concepts}
    VOCAB_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"vocab: {len(concepts)}개 → {VOCAB_FILE}")
    return supplement_vocab(llm, out, lines)


# ---------------------------------------------------------------- 2·3. 고르기 (자료 / 조항)

def pick(llm: LLM, vocab: list[dict], items: list[dict], what: str, batch: int, cache: dict,
         problems: list[str]) -> dict[str, list[dict]]:
    """items: [{id, text}] → {id: [{name, confidence}]} (목록에 있는 이름만, 최대 3개, confidence 높은 순)."""
    names = {c["name"] for c in vocab}
    vtext = vocab_text(vocab)
    vhash = sha([vtext, llm.model, PROMPT_VERSION, what])
    out, todo = {}, []
    for it in items:
        ck = sha([vhash, it["id"], it["text"]])
        it["_ck"] = ck
        if ck in cache:
            out[it["id"]] = cache[ck]
        else:
            todo.append(it)
    for i in range(0, len(todo), batch):
        group = todo[i:i + batch]
        text = "\n\n".join(f"(id: {it['id']})\n{it['text']}" for it in group)
        data = llm.ask(PICK_PROMPT.format(what=what, vocab=vtext, items=text))
        got = {str(r.get("id")): r.get("concepts") or [] for r in data.get("results", [])}
        for it in group:
            if it["id"] not in got:
                problems.append(f"{it['id']}: 응답에 없음 → 태그 0개")
            picked = []
            for c in got.get(it["id"], []):
                name = str(c.get("name", "")).strip()
                if name not in names:
                    problems.append(f"{it['id']}: 목록에 없는 개념 '{name}' 버림")
                    continue
                if any(p["name"] == name for p in picked):
                    continue
                try:
                    conf = min(1.0, max(0.0, float(c.get("confidence", 0))))
                except (TypeError, ValueError):
                    conf = 0.0
                picked.append({"name": name, "confidence": round(conf, 2)})
            picked.sort(key=lambda p: -p["confidence"])
            if len(picked) > MAX_TAGS:
                problems.append(f"{it['id']}: {len(picked)}개 → 상위 {MAX_TAGS}개만")
            out[it["id"]] = picked[:MAX_TAGS]
            if it["id"] in got:  # 응답에 빠진 자료는 캐시하지 않음 (다시 실행하면 다시 묻는다)
                cache[it["_ck"]] = out[it["id"]]
        print(f"  {what} {min(i + batch, len(todo))}/{len(todo)}")
    return out


def tag_documents(llm: LLM, vocab: dict, docs: list[dict], dry_run: bool) -> dict:
    cache = json.loads(TAG_CACHE.read_text(encoding="utf-8")) if TAG_CACHE.exists() else {}
    problems: list[str] = []
    items = [{"id": d["key"], "text": f"제목: {oneline(d['title'])}"
              + (f"\n쟁점: {oneline(d['issue'])}" if d["issue"] else "")
              + (f"\n내용: {oneline(d['body'])}" if d["body"] else "")} for d in docs]
    tags = pick(llm, vocab["concepts"], items, "자료", TAG_BATCH, cache, problems)
    TAG_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    if not dry_run:
        from psycopg.types.json import Jsonb  # noqa: F401  (psycopg 확인용)
        conn = connect(load_env())
        with conn.transaction():
            deleted = conn.execute("DELETE FROM case_tag WHERE axis = 'CONCEPT' AND source = 'LLM'").rowcount
            inserted = 0
            with conn.cursor() as cur:
                rows = [(d["id"], t["name"][:200], t["confidence"]) for d in docs for t in tags.get(d["key"], [])]
                cur.executemany("INSERT INTO case_tag (dispute_case_id, axis, value, source, confidence) "
                                "VALUES (%s, 'CONCEPT', %s, 'LLM', %s)", rows)
                inserted = len(rows)
        conn.close()
        print(f"case_tag CONCEPT/LLM: 삭제 {deleted}, 추가 {inserted}")
    return {"tags": tags, "problems": problems}


def query_concepts(llm: LLM, vocab: dict) -> dict:
    queries = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))["queries"]
    cache = (json.loads(QUERY_FILE.read_text(encoding="utf-8")).get("_cache", {}) if QUERY_FILE.exists() else {})
    problems: list[str] = []
    items = [{"id": q["id"], "text": oneline(q["query_text"])} for q in queries]  # 조항 원문만
    picked = pick(llm, vocab["concepts"], items, "약관 조항", QUERY_BATCH, cache, problems)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "model": llm.model, "temperature": 0,
           "prompt_version": PROMPT_VERSION, "input": "gold_queries.json 의 query_text 만 (clause_ref·정답·hint_cases 제외)",
           "problems": problems, "queries": {q["id"]: picked[q["id"]] for q in queries}, "_cache": cache}
    QUERY_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"query concepts → {QUERY_FILE} (문제 {len(problems)})")
    return out


# ---------------------------------------------------------------- v3: 약관 용어 정의로 보완 + 글자 일치 보조
#
#   policy  data/raw/_gold/policy_definitions_source.json (samsungfire.pdf 의 '용어의 정의' 구간만, pdftotext)
#           구간마다 GPT 로 정의된 용어 → {name, definition, synonyms(정의 문장 속 예시 포함)}
#           그다음 1회: 각 용어를 기존 80개 개념 중 같은 개념에 대응시키거나 새 개념으로 (기존 개념은 지우거나 이름을 바꾸지 않음)
#           같은 개념이면 동의어만 더하고 sources 에 policy_definition 추가 → concept_vocab_v3.json
#   tag3    v3 목록으로 GPT 선택(0~3개) + 글자 일치(제목·쟁점·내용 앞 1500자에 개념 이름·동의어가 그대로 나오면 추가)
#           → case_tag 의 axis='CONCEPT' 행을 전부 지우고 다시 넣음 (source='LLM'. 글자 일치 태그도 source 제약상 'LLM',
#             confidence 1.00. 어떤 방법으로 붙었는지는 concept_tags_v3.json)
#   query3  GPT 선택 + 글자 일치 합집합 → query_concepts_v3.json
#   글자 일치는 2글자 이상 동의어만 (1글자는 거의 모든 글에 나온다)

VOCAB_V3 = GOLD_DIR / "concept_vocab_v3.json"
POLICY_SOURCE = GOLD_DIR / "policy_definitions_source.json"
TAG_V3 = GOLD_DIR / "concept_tags_v3.json"
TAG_CACHE_V3 = GOLD_DIR / "concept_tag_cache_v3.json"
QUERY_V3 = GOLD_DIR / "query_concepts_v3.json"
POLICY_VERSION = "p4"  # p1: GPT 가 '근골격계 이학요법'을 '비급여 의료비'에 합침, 공백만 다른 중복·깨진 표 조각 이름
#                        p2: 글자 겹침 검사 추가 / p3: 이름 일치 합치기·새 용어끼리 접기, GPT 응답 캐시
POLICY_CACHE = GOLD_DIR / "concept_policy_cache.json"
MATCH_MIN_LEN = 2
TERM_NAME_MAX = 25     # 이보다 긴 용어 이름은 깨진 표 조각으로 보고 버림
EXACT_SYNONYM_MIN = 4  # 동의어가 기존 개념 이름과 같아 합칠 때, 그 이름이 이 길이 이상일 때만 ('입원' 같은 짧은 이름 제외)


def nospace(s: str) -> str:
    return "".join(s.split())


def lexical_overlap(term: dict, concept: dict) -> bool:
    """용어(이름·동의어)와 개념(이름·동의어) 중 하나라도 공백 빼고 서로 포함하면 True."""
    a = {nospace(x) for x in [term["name"]] + term["synonyms"] if len(nospace(x)) >= MATCH_MIN_LEN}
    b = {nospace(x) for x in [concept["name"]] + concept["synonyms"] if len(nospace(x)) >= MATCH_MIN_LEN}
    return any(x in y or y in x for x in a for y in b)

POLICY_PROMPT = """아래는 보험 약관의 '용어의 정의' 부분을 PDF 에서 뽑은 글이다. 표가 깨져서 용어 칸과 정의 칸이 떨어져 있을 수 있다.
정의된 용어마다 하나씩 아래 형식으로 정리하라.

- name: 약관에 정의된 용어 그대로 (예: 근골격계 이학요법, 체외충격파치료, 비급여 주사료)
- definition: 한 줄 정의 (약관 정의를 줄여서)
- synonyms: 같은 뜻으로 쓰이는 말 3~10개. 정의 문장 안에 나온 예시(구체적인 치료·시술·약제 이름)를 반드시 넣고,
  현장·분쟁에서 흔히 쓰는 말도 더하라 (예: 근골격계 이학요법 → 도수치료, 증식치료, FIMS, 신장분사치료, 비침습적 무통증 신호요법)
- 정의가 없는 표 제목·안내 문구는 빼라. 지어내지 마라

JSON 으로만 답하라: {{"terms": [{{"name": "...", "definition": "...", "synonyms": ["..."]}}]}}

[구간] {section}
{text}"""

MERGE_PROMPT = """[기존 개념]은 보험 분쟁 자료에서 뽑은 개념이고, [약관 용어]는 약관 '용어의 정의'에서 뽑은 용어다.
각 약관 용어가 기존 개념 중 하나와 같은 개념이면 그 기존 개념 이름을, 아니면 null 을 답하라.

- 같은 개념 = 같은 대상·같은 보장 내용을 가리키는 것. 넓은 개념에 좁은 용어를 억지로 넣지 마라
  (예: '근골격계 이학요법'은 '비급여 의료비'와 같은 개념이 아니다)
- 기존 개념 이름은 글자 그대로 써라

JSON 으로만 답하라: {{"mapping": [{{"term": "...", "concept": "기존 개념 이름 또는 null"}}]}}

[기존 개념]
{vocab}

[약관 용어]
{terms}"""


def build_vocab_v3(llm: LLM) -> dict:
    base = json.loads(VOCAB_FILE.read_text(encoding="utf-8"))
    src = json.loads(POLICY_SOURCE.read_text(encoding="utf-8"))
    input_hash = sha([base["concepts"], src["sections"], llm.model, POLICY_VERSION, POLICY_PROMPT, MERGE_PROMPT])
    if VOCAB_V3.exists():
        old = json.loads(VOCAB_V3.read_text(encoding="utf-8"))
        if old.get("input_hash") == input_hash:
            print(f"vocab v3: 캐시 사용 ({old['count']}개)")
            return old
    cache = json.loads(POLICY_CACHE.read_text(encoding="utf-8")) if POLICY_CACHE.exists() else {}

    def ask(prompt: str) -> dict:  # 같은 프롬프트·모델이면 다시 부르지 않음 (규칙만 바꿔 다시 돌릴 때 추출 결과가 흔들리지 않게)
        k = sha([prompt, llm.model])
        if k not in cache:
            cache[k] = llm.ask(prompt)
            POLICY_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        return cache[k]

    terms = []
    for sec in src["sections"]:
        got = ask(POLICY_PROMPT.format(section=sec["name"], text=sec["text"]))
        for t in clean_concepts({"concepts": got.get("terms", [])}):
            terms.append({**t, "section": sec["name"]})
        print(f"  policy {sec['name']}: 누적 {len(terms)}")
    # 이름이 너무 긴 것(깨진 표 조각)은 버리고, 공백만 다른 같은 용어는 하나로 (동의어·구간 합침)
    dropped = [t["name"] for t in terms if len(t["name"]) > TERM_NAME_MAX]
    uniq: dict[str, dict] = {}
    for t in terms:
        if len(t["name"]) > TERM_NAME_MAX:
            continue
        u = uniq.setdefault(nospace(t["name"]), {**t, "sections": [], "synonyms": []})
        if t["section"] not in u["sections"]:
            u["sections"].append(t["section"])
        u["synonyms"] += [s for s in t["synonyms"] if s not in u["synonyms"]]
    terms = list(uniq.values())
    # 새 용어끼리: 이름이 서로 앞부분이고 동의어가 하나라도 같으면 짧은 이름으로 합침 (예: 근골격계 이학요법 / …이학요법치료)
    folded = []
    terms.sort(key=lambda t: len(nospace(t["name"])))
    kept: list[dict] = []
    for t in terms:
        host = next((k for k in kept if nospace(t["name"]).startswith(nospace(k["name"]))
                     and {nospace(s) for s in t["synonyms"]} & {nospace(s) for s in k["synonyms"]}), None)
        if host:
            host["synonyms"] += [s for s in [t["name"]] + t["synonyms"] if s not in host["synonyms"] and s != host["name"]]
            host["sections"] += [s for s in t["sections"] if s not in host["sections"]]
            folded.append({"term": t["name"], "into": host["name"]})
        else:
            kept.append(t)
    terms = kept

    names = {c["name"] for c in base["concepts"]}
    by_base = {c["name"]: c for c in base["concepts"]}
    base_by_ns = {nospace(c["name"]): c["name"] for c in base["concepts"]}
    mapping, rejected, exact = {}, [], {}
    # 용어 이름·동의어가 기존 개념 이름과 (공백 빼고) 똑같으면 GPT 와 상관없이 그 개념으로 (예: 주사료 → 비급여 주사료)
    for t in terms:
        hit = next((base_by_ns[nospace(x)] for x in [t["name"]] + t["synonyms"] if nospace(x) in base_by_ns
                    and (x == t["name"] or len(nospace(x)) >= EXACT_SYNONYM_MIN)), None)
        if hit:
            exact[t["name"]] = hit
    got = ask(MERGE_PROMPT.format(vocab=vocab_text(base["concepts"]),
                                      terms="\n".join(f"- {t['name']}: {t['definition']}" for t in terms)))
    term_by_name = {t["name"]: t for t in terms}
    for m in got.get("mapping", []):
        term, concept = str(m.get("term", "")).strip(), m.get("concept")
        if concept not in names or term not in term_by_name:
            mapping[term] = None
            continue
        # 글자로 겹치는 데가 없는 합치기는 받지 않는다 (예: 근골격계 이학요법 → 비급여 의료비)
        if lexical_overlap(term_by_name[term], by_base[concept]):
            mapping[term] = concept
        else:
            mapping[term] = None
            rejected.append({"term": term, "proposed": concept, "reason": "이름·동의어가 글자로 겹치지 않음 → 새 개념"})
    for term, concept in exact.items():
        if mapping.get(term) != concept:
            mapping[term] = concept

    concepts = [{**c, "sources": ["dispute"]} for c in base["concepts"]]
    by_name = {c["name"]: c for c in concepts}
    merged, added = [], []
    for t in terms:
        target = mapping.get(t["name"])
        if target:
            c = by_name[target]
            extra = [s for s in [t["name"]] + t["synonyms"] if s not in c["synonyms"] and s != c["name"]]
            c["synonyms"] = c["synonyms"] + extra
            if "policy_definition" not in c["sources"]:
                c["sources"].append("policy_definition")
            c.setdefault("policy_terms", []).append(t["name"])
            merged.append({"term": t["name"], "into": target, "synonyms_added": extra})
        elif t["name"] in by_name:  # 이름이 이미 같음
            continue
        else:
            c = {"name": t["name"], "definition": t["definition"], "synonyms": t["synonyms"],
                 "sources": ["policy_definition"], "policy_sections": t["sections"]}
            concepts.append(c)
            by_name[c["name"]] = c
            added.append(t["name"])
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "model": llm.model, "temperature": 0,
           "version": "v3", "input_hash": input_hash,
           "base": {"file": VOCAB_FILE.name, "count": len(base["concepts"])},
           "policy": {"source_pdf": src["source_pdf"], "sections": [s["name"] for s in src["sections"]],
                      "terms_extracted": len(terms), "dropped_long_names": dropped, "folded_new_terms": folded,
                      "exact_name_merges": exact,
                      "merge_rejected": rejected, "merged_into_existing": merged, "added": added,
                      "terms": terms},
           "prompts": {"policy": POLICY_PROMPT, "merge": MERGE_PROMPT},
           "count": len(concepts), "count_by_source": {
               "dispute_only": sum(1 for c in concepts if c["sources"] == ["dispute"]),
               "dispute+policy_definition": sum(1 for c in concepts if len(c["sources"]) == 2),
               "policy_definition_only": sum(1 for c in concepts if c["sources"] == ["policy_definition"])},
           "concepts": concepts}
    VOCAB_V3.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"vocab v3: 용어 {len(terms)}개 → 합침 {len(merged)}, 새로 {len(added)} → {len(concepts)}개")
    return out


def literal_matches(vocab: list[dict], text: str) -> dict[str, list[str]]:
    """개념 이름·동의어(2글자 이상)가 글에 그대로 나오면 {개념: [일치한 말]}."""
    out = {}
    for c in vocab:
        hits = [w for w in dict.fromkeys([c["name"]] + c["synonyms"]) if len(w) >= MATCH_MIN_LEN and w in text]
        if hits:
            out[c["name"]] = hits
    return out


def combine(llm_tags: list[dict], matches: dict[str, list[str]]) -> list[dict]:
    """GPT 선택 ∪ 글자 일치. 같은 개념이면 하나로 (confidence 는 GPT 값과 1.0 중 큰 값)."""
    out: dict[str, dict] = {}
    for t in llm_tags:
        out[t["name"]] = {"name": t["name"], "confidence": t["confidence"], "methods": ["llm"]}
    for name, words in matches.items():
        e = out.setdefault(name, {"name": name, "confidence": 0.0, "methods": []})
        e["methods"].append("literal")
        e["matched"] = words
        e["confidence"] = max(e["confidence"], 1.0)
    return sorted(out.values(), key=lambda e: (-e["confidence"], e["name"]))


def tag_documents_v3(llm: LLM, vocab: dict, docs: list[dict], dry_run: bool) -> dict:
    cache = json.loads(TAG_CACHE_V3.read_text(encoding="utf-8")) if TAG_CACHE_V3.exists() else {}
    problems: list[str] = []
    texts = {d["key"]: f"제목: {oneline(d['title'])}" + (f"\n쟁점: {oneline(d['issue'])}" if d["issue"] else "")
             + (f"\n내용: {oneline(d['body'])}" if d["body"] else "") for d in docs}
    picked = pick(llm, vocab["concepts"], [{"id": k, "text": t} for k, t in texts.items()], "자료", TAG_BATCH, cache,
                  problems)
    TAG_CACHE_V3.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tags = {d["key"]: combine(picked.get(d["key"], []), literal_matches(vocab["concepts"], texts[d["key"]]))
            for d in docs}
    TAG_V3.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "vocab": VOCAB_V3.name,
                                  "match_min_len": MATCH_MIN_LEN, "problems": problems, "tags": tags},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    if not dry_run:
        conn = connect(load_env())
        with conn.transaction():
            deleted = conn.execute("DELETE FROM case_tag WHERE axis = 'CONCEPT'").rowcount
            rows = [(d["id"], t["name"][:200], round(t["confidence"], 2)) for d in docs for t in tags[d["key"]]]
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO case_tag (dispute_case_id, axis, value, source, confidence) "
                                "VALUES (%s, 'CONCEPT', %s, 'LLM', %s)", rows)
        conn.close()
        print(f"case_tag CONCEPT: 삭제 {deleted}, 추가 {len(rows)}")
    return {"tags": tags, "problems": problems}


def query_concepts_v3(llm: LLM, vocab: dict) -> dict:
    queries = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))["queries"]
    cache = json.loads(QUERY_V3.read_text(encoding="utf-8")).get("_cache", {}) if QUERY_V3.exists() else {}
    problems: list[str] = []
    items = [{"id": q["id"], "text": oneline(q["query_text"])} for q in queries]  # 조항 원문만
    picked = pick(llm, vocab["concepts"], items, "약관 조항", QUERY_BATCH, cache, problems)
    result = {q["id"]: combine(picked[q["id"]], literal_matches(vocab["concepts"], oneline(q["query_text"])))
              for q in queries}
    old = json.loads(QUERY_FILE.read_text(encoding="utf-8"))["queries"] if QUERY_FILE.exists() else {}
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "model": llm.model, "temperature": 0,
           "vocab": VOCAB_V3.name, "input": "gold_queries.json 의 query_text 만 (clause_ref·정답·hint_cases 제외)",
           "method": "GPT 선택(0~3) ∪ 글자 일치(개념 이름·2글자 이상 동의어)",
           "zero_concept_queries": {"v1": [q for q in old if not old[q]], "v3": [q for q in result if not result[q]]},
           "problems": problems, "queries": result, "_cache": cache}
    QUERY_V3.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"query concepts v3 → {QUERY_V3} (개념 0개: v1 {len(out['zero_concept_queries']['v1'])} → "
          f"v3 {len(out['zero_concept_queries']['v3'])})")
    return out


# ---------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description="개념 태그 (vocab / tag / query / all, v3: policy / tag3 / query3 / all3)")
    parser.add_argument("stage", choices=["vocab", "tag", "query", "all", "policy", "tag3", "query3", "all3"])
    parser.add_argument("--dry-run", action="store_true", help="tag·tag3: case_tag 에 쓰지 않음")
    args = parser.parse_args()

    conn = connect(load_env())
    conn.execute("SET default_transaction_read_only = on")
    docs = load_docs(conn)
    conn.close()
    llm = LLM()
    print(f"model={llm.model} ({llm.model_source}), 자료 {len(docs)}건")
    if args.stage in ("policy", "tag3", "query3", "all3"):
        try:
            v3 = (build_vocab_v3(llm) if args.stage in ("policy", "all3")
                  else json.loads(VOCAB_V3.read_text(encoding="utf-8")))
            if args.stage in ("tag3", "all3"):
                res = tag_documents_v3(llm, v3, docs, args.dry_run)
                print(f"tag3 problems: {len(res['problems'])}")
            if args.stage in ("query3", "all3"):
                query_concepts_v3(llm, v3)
        finally:
            u = llm.record(args.stage)
            print(f"LLM 호출 {u['calls']}, 토큰 {u['prompt_tokens']:,}+{u['completion_tokens']:,}, 비용 ${u['cost_usd']}")
        return
    try:
        vocab = (build_vocab(llm, docs) if args.stage in ("vocab", "all")
                 else json.loads(VOCAB_FILE.read_text(encoding="utf-8")))
        if args.stage in ("tag", "all"):
            res = tag_documents(llm, vocab, docs, args.dry_run)
            (RAW_DIR / "_report" / "concept_tag_problems.json").write_text(
                json.dumps(res["problems"], ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"tag problems: {len(res['problems'])}")
        if args.stage in ("query", "all"):
            query_concepts(llm, vocab)
    finally:  # 실패해도 쓴 토큰은 기록
        u = llm.record(args.stage)
        print(f"LLM 호출 {u['calls']}, 토큰 {u['prompt_tokens']:,}+{u['completion_tokens']:,}, 비용 ${u['cost_usd']}")


if __name__ == "__main__":
    sys.exit(main())
