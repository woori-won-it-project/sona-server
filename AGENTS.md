# AGENTS.md

Claude Code, Codex 등 AI 도구가 이 저장소에서 지켜야 하는 규칙.

## 작업 시작

- 작업 전에 `SPEC.md`를 읽는다. 분쟁 자료 검색·질문 생성 작업이면 SPEC.md 8장을 꼭 확인한다.
- 브랜치는 이슈에서 만든다. 이름은 `{type}/{이슈번호}-{영문-요약}` (예: `feat/23-s3-document-registration`), 기준은 `dev`.
- 현재 브랜치가 `dev` 또는 `main`이면 파일을 고치기 전에 멈추고 알린다.
- `SPEC.md` '확정된 결정'과 다르게 해야 하면, 하기 전에 먼저 묻는다.

## 커밋 메시지

- 형식: `TYPE: 요약` (TYPE 은 대문자)
- TYPE: `FEAT`, `FIX`, `REFACTOR`, `DOCS`, `TEST`, `CHORE`, `CI`, `BUILD`, `STYLE`, `PERF`
- 예: `FEAT: 분쟁조정 결정례 수집 기능 추가 - decision.py 작성`
- 커밋 전에 Java 코드를 바꿨다면 `./gradlew spotlessApply` 를 실행한다.

## 끝내기 전 검사

- Java 를 바꿨으면 `api-spring` 에서 `./gradlew build` 가 통과해야 한다 (테스트 + 코드 정렬 검사).
- `scripts/` 를 바꿨으면 바꾼 파이썬 파일이 문법 오류 없이 실행되는지 확인한다.
- 분쟁 자료 검색 로직을 바꿨으면 정답지로 평가를 돌려 recall@10 이 떨어지지 않았는지 확인한다.

## PR

- PR 제목은 커밋 메시지와 같은 형식 (squash merge 시 dev 의 커밋 메시지가 됨)
- PR 본문은 GitHub PR 템플릿 양식을 그대로 채운다:
  - 관련 이슈 (`Closes #번호`)
  - 작업 요약 (무엇을, 왜)
  - PR 유형 (해당 항목 모두 체크)
  - 주요 변경 사항
  - 스크린샷 (선택)
  - 리뷰 요청 사항 (선택)
  - PR Checklist
- 스키마(`infra/init.sql`) 변경이 있으면 리뷰 요청 사항에 "로컬 DB 재생성 필요 여부"를 적는다.
- 무언가를 새로 정한 PR 이면 `SPEC.md` '확정된 결정'에 한 줄을 추가한다.
- 대상 브랜치: 기능 브랜치 → `dev`

## 문서 수정

- `AGENTS.md`, `SPEC.md` 는 바로 고치지 않는다. 바꿀 줄과 이유를 먼저 보여주고, 승인받은 뒤 고친다.
- 작업 중 `SPEC.md` 와 코드가 다른 걸 발견하면 멈추고 알린다. 임의로 한쪽에 맞추지 않는다.
- '확정된 결정' 표는 줄을 지우지 않는다. 바뀐 결정은 옛 줄에 "→ 날짜 변경"을 적고 새 줄을 추가한다.

## 데이터와 스키마

- 스키마는 `infra/init.sql` 에서만 바꾼다. `spring.jpa.hibernate.ddl-auto` 는 `validate` 를 유지한다.
- 지식 테이블(`dispute_case`, `case_chunk`, `case_tag`)은 읽기만 한다. INSERT·UPDATE·DELETE 하지 않고, JPA Entity 를 만들지 않는다 (ID 저장 + JdbcTemplate/native query).
- `case_chunk.id` 는 데이터를 다시 자르면 바뀐다. 근거를 저장할 때는 `evidence_text`(글 복사본)를 함께 저장한다.
- 임베딩은 `text-embedding-3-small`(1536차원)만 쓴다. 다른 모델로 만든 벡터와 섞지 않는다.

## LLM 과 프로필

- LLM 을 부르는 기능은 `mock` 프로필(기본 `LLM_PROVIDER=mock`)에서도 동작해야 한다. 가짜 응답 구현을 함께 만든다.
- `mock` 프로필에는 지식 테이블이 없다. 검색을 쓰는 기능은 mock 에서 가짜 결과를 돌려준다.
- 프롬프트는 `resources/prompts/` 에 버전을 붙인 파일로 둔다 (예: `persona_read_v1.md`). 내용을 바꾸면 새 버전 파일을 만든다.

## 보안

- `.env`, `data/raw`, `dumps`, `*.dump`, `*.hwp`, 금감원 원문 데이터는 절대 커밋하지 않는다.
- API 키·비밀번호를 코드, 설정 파일, 커밋 메시지, PR 본문에 쓰지 않는다. 새 환경변수는 `.env.example` 에 키 이름만 추가한다. 운영 값은 Parameter Store(`/sona/prd/`)에 둔다.
- 테스트는 공용 DB 에 연결하지 않는다.
