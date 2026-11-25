# AGENTS.md

Claude Code, Codex 등 AI 도구가 이 저장소에서 지켜야 하는 규칙.

## 커밋 메시지

- 형식: `TYPE: 요약` (TYPE 은 대문자)
- TYPE: `FEAT`, `FIX`, `REFACTOR`, `DOCS`, `TEST`, `CHORE`, `CI`, `BUILD`, `STYLE`, `PERF`
- 예: `FEAT: 분쟁조정 결정례 수집 기능 추가 - decision.py 작성`
- 커밋 전에 Java 코드를 바꿨다면 `./gradlew spotlessApply` 를 실행한다.

## PR

- PR 제목은 커밋 메시지와 같은 형식 (squash merge 시 dev 의 커밋 메시지가 됨)
- PR 본문은 GitHub PR 템플릿 양식을 그대로 채운다:
  - 관련 이슈
  - 작업 요약 (무엇을, 왜)
  - PR 유형 (해당 항목 모두 체크)
  - 주요 변경 사항
  - 스크린샷 (선택)
  - 리뷰 요청 사항 (선택)
  - PR Checklist
- 스키마(`infra/init.sql`) 변경이 있으면 리뷰 요청 사항에 "로컬 DB 재생성 필요 여부"를 적는다.
- 대상 브랜치: 기능 브랜치 → `dev`

## 보안

- `.env`, `data/raw`, `dumps`, `*.dump`, `*.hwp`, 금감원 원문 데이터는 절대 커밋하지 않는다.
- API 키·비밀번호를 코드, 설정 파일, 커밋 메시지, PR 본문에 쓰지 않는다. 새 환경변수는 `.env.example` 에 키 이름만 추가한다.
- 테스트는 공용 DB 에 연결하지 않는다.
- `spring.jpa.hibernate.ddl-auto` 는 `validate` 를 유지한다.
