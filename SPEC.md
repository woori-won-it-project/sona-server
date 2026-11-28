# SPEC.md

> Sona 서버가 **무엇을 만드는지**와 **지금까지 정한 것**을 적는 문서다. 작업 규칙은 `AGENTS.md`에 있다.
> 기준: `dev` a36fcbf (2026-11-28). 문서와 코드가 다르면 코드가 기준이고, 문서를 고친다.

## 1. 개요

Sona는 보험사 담당자가 **약관·상품설명서를 올리면, 소비자가 오해할 만한 부분을 미리 찾아 주는 B2B 서비스**다.

1. 금감원 분쟁조정 자료(사례·해결기준·결정례)에서 비슷한 분쟁을 찾아 **점검 질문**을 만든다.
2. 담당자가 질문과 기준 답(예/아니오)을 고르고 승인한다.
3. 서로 다른 **페르소나**(가상 소비자)가 상품설명서를 읽고 질문에 답한다.
4. 오답률로 오해 위험을 보여 주고, 설명서 **수정 제안**을 만든다.
5. 설명서를 고쳐 다시 올리면 **같은 조건으로 재실험**해 전후를 비교한다.

## 2. 기술 스택

| 영역 | 선택 | 버전 |
|---|---|---|
| 언어·프레임워크 | Java, Spring Boot (Gradle wrapper) | 21, 3.5.16, 9.9.2 |
| DB | PostgreSQL + pgvector + pg_trgm | 16 (pgvector 0.8.7) |
| 메시징·캐시 | RabbitMQ, Redis | 3.13.7, 7.4.12 |
| 임베딩 | OpenAI `text-embedding-3-small` | 1536차원 |
| LLM (페르소나·생성) | OpenAI GPT (모델 미정), 기본값 `mock` | 설정 `sona.llm.*`. 현재 코드는 Claude 연동이라 GPT로 바꿔야 함 |
| 데이터 수집·가공 | Python (`scripts/`) | 3.11 |
| 코드 정렬 | Spotless + palantir-java-format | 2.103.0 |
| 운영 | AWS (ECR, RDS, Parameter Store `/sona/prd/`) | `infra/prod/` |

## 3. 구조

### 폴더

| 경로 | 내용 |
|---|---|
| `api-spring/` | Spring 서버 |
| `scripts/collector/` | 금감원 자료 수집·청킹·임베딩·검색 평가 (Python) |
| `infra/init.sql` | **스키마의 유일한 기준.** `ddl-auto`는 `validate` |
| `infra/docker-compose.yml` | 로컬 인프라 (postgres, rabbitmq, redis) |
| `infra/prod/` | 운영 compose |

### 패키지 (`com.sona.api`)

기능별 패키지 아래에 `api`(컨트롤러·요청/응답) / `application`(서비스) / `domain`(엔티티·리포지토리)을 둔다.

| 패키지 | 역할 |
|---|---|
| `global` | 공통 응답·에러, 인증, 설정, LLM 클라이언트 |
| `member` | 사번 로그인 |
| `review` | 검수(한 번의 점검 작업)와 진행 단계 |
| `document` | 약관·설명서 파일, 조항 |
| `question` | 점검 질문, 3지선다 보기, 근거 |
| `persona` | 페르소나와 읽기 엔진 |
| `experiment` | 실험 실행·응답·채점 |
| `revision` | 수정 제안 |

### 프로필

| 프로필 | 용도 |
|---|---|
| `local` (기본) | 로컬 Docker DB·RabbitMQ·Redis |
| `mock` | H2 메모리 DB + 가짜 데이터. 외부 연결 없이 화면 개발용. **지식 테이블 없음** |
| `prod` | 운영. 비밀값은 Parameter Store |
| `test` | 테스트 (`application-test.yml`) |

### 테이블

| 묶음 | 테이블 | 소유 |
|---|---|---|
| 지식 데이터 | `dispute_case`, `case_chunk`, `case_tag` | 데이터 담당. **서비스는 읽기만** → 8장 |
| 서비스 | `members`, `reviews`, `documents`, `clauses`, `questions`, `question_options`, `question_evidences`, `personas`, `review_personas`, `experiments`, `experiment_documents`, `experiment_responses`, `reading_memos`, `revision_suggestions` | 서비스 |

검수(`reviews`)를 지우면 딸린 데이터가 모두 지워진다 (`ON DELETE CASCADE`).

## 4. 용어

| 용어 | 뜻 |
|---|---|
| 검수 (review) | 상품 하나를 점검하는 한 번의 작업 |
| 약관 / 상품설명서 | `TERMS` / `PRODUCT_GUIDE` (특약 `SPECIAL_TERMS`) |
| 조항 (clause) | 약관 안의 한 덩어리 (예: 제11조) |
| 분쟁 자료 | 금감원 사례(`CASE`) / 해결기준(`STANDARD`) / 결정례(`DECISION`) |
| 청크 (chunk) | 검색용으로 자른 분쟁 자료 조각 |
| 질문 출처 | `CASE_BASED`(분쟁사례 기반) / `MISUNDERSTANDING`(AI 예상 오해) / `MANUAL`(담당자 작성) |
| 기준 답 | 질문의 정답 `YES` / `NO` |
| 페르소나 | 가상 소비자. 금융 지식, 나이대, 꼼꼼함, 정보 경로, 성향으로 구분 |
| 정보 경로 | `GUIDE`(설명서를 직접 읽음) / `AGENT_TALK`(설계사 설명을 들음). **페르소나는 약관을 보지 않는다** |
| 읽기 메모 | 페르소나가 읽고 남긴 메모. 답할 때는 설명서 없이 메모만 본다 |
| 오해율 | (오답 + 판단 불가) / 전체 × 100 |
| critical 오해 | 실제보다 더 받는다고 믿는 오해 |
| 실험 | `INITIAL`(첫 실험) / `RERUN`(수정 후 재실험) |

## 5. 검수 흐름 (`reviews.current_step`)

```
DOC_UPLOAD → ANALYZING → QUESTION_SELECT → ANSWER_APPROVE → PERSONA_SELECT
  → EXPERIMENT → REPORT → REVISION → REUPLOAD → (EXPERIMENT 재실험)
```

- `ANALYZING`, `EXPERIMENT`는 처리 중 표시와 중복 실행 방지에 쓴다.
- 첫 실험 이후에는 질문·기준 답·페르소나를 바꿀 수 없고, 상품설명서만 다시 올릴 수 있다.

## 6. API 공통 규칙

| 항목 | 규칙 |
|---|---|
| 경로 | `/api/v1/...` (헬스체크만 `/api/health`) |
| 성공 응답 | `{"data": ...}` (`ApiResponse`) |
| 에러 응답 | `{"code", "message", "details"}` (`ErrorResponse`). 프론트는 `code`로 분기, `message`는 그대로 표시 가능 |
| 에러 코드 | `global/error/ErrorCode.java`가 목록의 기준 |
| 인증 | 사번 로그인 (`/api/v1/auth/login`). JWT + Redis는 진행 중 |
| API 명세 | Swagger (`/swagger-ui/index.html`) + 팀 api.md |

## 7. 페르소나 실험

| 항목 | 정한 것 |
|---|---|
| 페르소나 속성 | 금융 지식 LOW/MEDIUM/HIGH, 나이대 20·40·60대(근거: 2024 전국민 금융이해력 조사), 꼼꼼함 0~1, 정보 경로 GUIDE/AGENT_TALK, 성향 낙관/신중 (50:50) |
| 읽기 | 문장마다 읽힐 확률을 계산한다 (꼼꼼함·위치·형식·보장/예외 문장). 놓친 문장은 빠지고, 다 못 읽은 문장은 '…', 모르는 낱말은 '□□'로 보인다. 확률 값은 모두 가정값 (`ReadingRules`) |
| 답하기 | 메모만 보고 3지선다 (정답 1 + 오해 2)를 고른다 |
| 채점 | 코드로 한다. LLM을 쓰지 않는다 (`Grader`) |
| 보기 | 첫 실험 때 한 번 만들고 재실험에도 그대로 쓴다. 정답 위치는 질문 id로 고정 |
| 재현성 | 같은 조건이면 같은 결과가 나오도록 시드를 고정한다 (`SeededRandom`) |

## 8. 분쟁 자료 검색 (RAG)

약관 조항 하나를 넣으면 비슷한 금감원 분쟁사례를 찾는다. **질문 만들기와 근거 보여주기**에 쓴다. 페르소나는 이 데이터를 쓰지 않는다 (설명서만 본다). 데이터 담당: 승태.

### 8.1 테이블 (지식 테이블)

| 테이블 | 내용 | 주로 쓰는 컬럼 |
|---|---|---|
| `dispute_case` | 분쟁 자료 1건 | `doc_kind`(CASE/STANDARD/DECISION), `category`(검색은 항상 `보험`), `title`, `source_url`, `complaint`(**소비자가 믿은 것**), `dispute_issue`(쟁점), `decision_reason`(**실제 판단**), `consumer_warning` |
| `case_chunk` | 검색용 조각 + 임베딩 | `dispute_case_id`, `chunk_type`, `content`(앞에 `[안건명]`), `embedding`(vector 1536) |
| `case_tag` | 자료 태그 | `axis='CONCEPT'` = 개념 태그 (검색 보정용) |

- 서비스는 **읽기만** 한다. JPA Entity를 만들지 않고 `JdbcTemplate`·native query로 읽는다.
- 데이터는 dump로 받는다 (`bash scripts/db-restore.sh dumps/<파일>`). `mock` 프로필에는 이 테이블이 없으므로 가짜 검색 결과를 돌려준다.

### 8.2 검색 순서 (확정)

1. 조항 원문을 `text-embedding-3-small`(1536)로 임베딩한다. 모델이 다르면 결과가 의미 없다.
2. 후보를 종류별로 따로 뽑는다: 사례·해결기준 조각 상위 50개, 결정례 조각 상위 50개 (`DECISION_CLAUSE` 제외 — 약관 원문이라 아무 조항과도 비슷하게 나온다).
3. 자료 단위 점수 = `0.7 × (1 - 가장 가까운 거리) + 0.3 × 가장 높은 word_similarity`
4. 개념 태그 보정: 조항 개념과 자료 개념이 겹치면 +0.10 (자료 10% 넘게 붙은 흔한 개념 제외). 개념 목록 파일은 데이터 담당이 `resources/`로 넘길 예정이며, 그 전에는 1~3, 5번만으로 구현해도 된다.
5. 최종: **사례·해결기준 상위 14 + 결정례 상위 6 = 20건**

```sql
-- 2번 후보 (사례·해결기준). 결정례는 doc_kind = 'DECISION' AND chunk_type <> 'DECISION_CLAUSE'
SELECT c.id, c.dispute_case_id, d.doc_kind, d.title,
       c.embedding <=> CAST(:vec AS vector) AS distance,
       word_similarity(:clauseText, c.content) AS keyword
FROM case_chunk c
JOIN dispute_case d ON d.id = c.dispute_case_id
WHERE d.category = '보험'
  AND d.doc_kind IN ('CASE', 'STANDARD')
  AND c.embedding IS NOT NULL
ORDER BY c.embedding <=> CAST(:vec AS vector)
LIMIT 50;
```

- 검증: 평가 조항 33개 정답표(v5, 1,024쌍) 기준 recall@20 0.942 (capped 0.947), 정답을 못 찾는 조항 0개. Spring 구현 후 파이썬 결과와 순위가 같은지 확인한다.
- 순위·점수는 화면에 보여주지 않는다. LLM에 넘길 근거를 고르는 용도다.

### 8.3 질문 만들기에 쓸 때 (`CASE_BASED`)

흐름: 조항 → 8.2 검색 20건 → LLM이 예·아니오 질문 + 기준 답(YES/NO) + 이유 생성 → 저장. **아직 구현 전이다.**

| 항목 | 정한 것 |
|---|---|
| 관련 없는 자료 | 20건 중 약 80%는 관련 없다. 프롬프트에 **"조항과 관련 없는 사례는 무시하라"** 지시를 반드시 넣는다 |
| LLM에 넘길 칸 | `complaint`(소비자가 믿은 것)와 `decision_reason`(실제 판단)이 질문의 핵심 재료다 |
| 오해 보기 | `complaint`를 같이 주면 지어낸 오해가 아니라 **실제로 분쟁 난 오해**가 된다 |
| 질문 저장 | `questions.source_type = CASE_BASED`, `reference_answer` YES/NO |
| 보기 저장 | `question_options`: 정답 1 + 오해 2, 위험한 오해는 `is_critical` |
| 근거 저장 | `question_evidences`: `clause_id`, `case_chunk_id`(ID만) + **`evidence_text`(글 복사본) 필수**. 데이터를 다시 자르면 조각 ID가 바뀌고 FK는 `ON DELETE SET NULL`이라, 근거 글은 복사본으로 남긴다 |
| LLM | OpenAI GPT (임베딩과 같은 `OPENAI_API_KEY`). mock에서도 돌아가야 한다 |
| 프롬프트 | 버전을 붙인 파일로 관리한다 (AGENTS.md) |

## 9. 확정된 결정

> 무언가를 새로 정한 PR은 이 표에 한 줄을 추가한다. 바뀐 결정은 지우지 않고 "→ 날짜 변경"을 적는다.

| 날짜 | 정한 것 | 이유 |
|---|---|---|
| 2026-11-23 | 저장소 2개 (server, front). FastAPI 없이 Spring 하나 | 배포·관리 대상을 줄이고, LLM은 HTTP 호출이라 Spring으로 충분 |
| 2026-11-23 | 스키마는 `infra/init.sql`이 기준, `ddl-auto: validate` | 어느 PC에서나 같은 구조. JPA가 몰래 스키마를 바꾸지 않게 |
| 2026-11-23 | 사번 로그인 (소셜 로그인 없음) | B2B 내부 사용자 |
| 2026-11-25 | 분쟁 검색: 종류별 후보 분리 7+3, 벡터 0.7/키워드 0.3, 개념 태그 보정 | 결정례가 후보를 독차지하는 문제 해결, recall@10 0.706 → 0.836 |
| 2026-11-28 | 검색 결과 개수 K=10 → 20 (14+6) | recall 0.80 → 0.94, 못 찾는 조항 1 → 0. K=30은 +0.005뿐. 대신 precision 0.31 → 0.20이라 질문 생성에서 무관 사례 무시 지시 필요 |
| 2026-11-25 | 지식 테이블 3개 (`crawl_job`, `gold_*` 삭제) | 서비스가 쓰지 않는 테이블 정리. 정답지는 파일로 관리 |
| 2026-11-25 | 커밋·PR 제목 `TYPE: 요약` (대문자), dev 머지는 Squash | 기록 통일, PR 하나 = 기능 하나 |
| 2026-11-25 | 코드 정렬 Spotless + palantir. 로컬 자동 정렬, CI는 검사만 | 사람마다 다른 코드 모양 방지 |
| 2026-11-25 | 비밀값 유출 방지는 GitHub Push protection | push 단계에서 막아 공개 저장소에 키가 남지 않게 |
| 2026-11-27 | 운영: RDS(PostgreSQL), ECR, Parameter Store | 관리형 DB·이미지 저장소, 비밀값 분리 |
| 2026-11-28 | 페르소나 LLM도 OpenAI GPT로 통일 (11-27 Claude 안 철회) | 임베딩과 같은 키·결제 하나로 관리 |
| 2026-11-27 | 이슈 브랜치 자동 생성 Action 제거, 수동 생성 유지 | 이름 규칙이 사람 입력에 달려 있어 자동화 이득이 적음 |
| 2026-11-27 | 페르소나는 설명서만 읽고, 메모 → 3지선다, 코드 채점 | (이유 기록 필요) |

## 10. 아직 정하지 않은 것

- 질문 생성(`CASE_BASED`, `MISUNDERSTANDING`)과 Spring 검색(8.2) 구현 담당
- 질문 생성 때 LLM에 넘길 입력 형식 (20건 전체 / 사례별 어떤 칸)
- 조항 개념 뽑기 방식과 개념 목록 파일 위치 (`resources/`)
- 만든 질문이 좋은지 확인하는 기준
- 페르소나 LLM을 GPT로 바꾸는 작업 담당 (현재 코드는 Claude 연동)
- 분쟁사례의 "소비자가 믿은 것 / 실제 판단"을 질문 재료로 정리하는 방식
- 실험 실행을 RabbitMQ 큐로 옮기는 시점 (지금은 스레드 풀)
- 공용 개발 DB 운영 방식

## 11. 참고 문서

| 문서 | 위치 | 비고 |
|---|---|---|
| 기능 명세 (코드 주석의 `spec x.x`) | 팀 노션 | 이 SPEC.md와 다른 문서. 장 번호는 그 문서 기준 |
| API 명세 (코드 주석의 `api.md`) | 팀 노션 v0.4 | Swagger와 함께 확인 |
| ERD | sona-v2 최종본 | `infra/init.sql`이 기준 |
| 실행 방법 | `README.md` | |
