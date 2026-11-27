# Sona Server

보험 약관·설명서 문구를 금감원 분쟁조정 사례와 대조해 소비자 오해 소지를 검증하는 B2B 서비스 **Sona**의 백엔드 모노레포입니다.

## 폴더 구조

```
server/
├── api-spring/        # Spring Boot API (+ Dockerfile)
├── scripts/
│   ├── db-dump.ps1 / db-dump.sh        # 로컬 DB → dumps/sona_YYYY-MM-DD.dump
│   ├── db-restore.ps1 / db-restore.sh  # dump 파일 → 로컬 DB
│   └── collector/     # 금감원 데이터 수집·청크·임베딩 (Python, 일회성)
├── infra/
│   ├── docker-compose.yml
│   └── init.sql       # DB 스키마 (스키마의 단일 소유자)
├── dumps/             # dump 파일 위치 (커밋 금지)
├── data/raw/          # 원본 파일 위치 (커밋 금지)
└── .env.example
```

## 기술 스택

| 영역 | 스택 | 버전 |
|---|---|---|
| API | Java (Gradle toolchain) | 21 |
| | Spring Boot | 3.5.16 |
| | Gradle (wrapper) | 9.9.2 |
| | springdoc-openapi-starter-webmvc-ui | 2.10.1 |
| | Spring Data JPA, Validation, Actuator, AMQP, Data Redis, Lombok | Spring Boot BOM 관리 |
| 임베딩 | OpenAI `text-embedding-3-small` (1536차원) | Spring 설정 `sona.embedding.*` |
| 스크립트 | Python (`scripts/` 수집·임베딩) | 3.11 |
| DB | PostgreSQL + pgvector | `pgvector/pgvector:pg16` (pgvector 0.8.7) |
| 메시징 | RabbitMQ | `rabbitmq:3.13.7-management` |
| 캐시 | Redis | `redis:7.4.12` |
| 앱 이미지 | Spring 빌드 / 실행 | `eclipse-temurin:21-jdk` / `eclipse-temurin:21-jre` |
| 인프라 | Docker Compose | |

버전을 바꿀 때는 이 표와 함께 `api-spring/build.gradle`, `api-spring/gradle/wrapper/gradle-wrapper.properties`, `api-spring/Dockerfile`, `infra/docker-compose.yml`을 같이 수정합니다.

## 사전 설치

- **공통(필수)**: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- **백엔드 개발자 추가**: Java 21, IntelliJ IDEA
- **수집·임베딩 스크립트 실행 시에만**: Python 3.11

## 처음 한 번: `.env` 만들기

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# Mac
cp .env.example .env
```

`.env`를 열어 `POSTGRES_PASSWORD`, `RABBITMQ_PASSWORD`에 **로컬용 아무 값**이나 채웁니다. 값이 비어 있으면 compose가 실행되지 않습니다. 임베딩(OpenAI)을 쓸 때만 `OPENAI_API_KEY`를 채우면 됩니다.

> `.env`는 절대 커밋하지 않습니다. `.gitignore`에 등록되어 있습니다.

## 실행 방법

모든 명령은 **레포 루트(`server/`)** 에서 실행합니다.

### A. 백엔드 개발자: 인프라는 Docker, 앱은 IDE에서 실행

1) 인프라(postgres, rabbitmq, redis) 띄우기

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d
```

2) Spring API: IntelliJ에서 `api-spring` 폴더를 Gradle 프로젝트로 열고 `ApiApplication`을 실행합니다. 터미널에서 실행하려면 다음과 같이 합니다.

```powershell
# Windows PowerShell
cd api-spring; .\gradlew.bat bootRun
```

```bash
# Mac
cd api-spring && ./gradlew bootRun
```

루트 `.env`를 자동으로 읽기 때문에 IntelliJ에 환경변수를 따로 넣지 않아도 됩니다. 기본 프로필은 `local`입니다.

### B. 프론트 개발자: 백엔드 전체를 컨테이너로

```bash
docker compose -f infra/docker-compose.yml --env-file .env --profile app up -d --build
```

끝입니다. 종료할 때는 `--profile app down`을 실행합니다(데이터는 유지됩니다).

### 접속 주소

| 대상 | 주소 |
|---|---|
| Spring health | http://localhost:8080/api/health |
| Swagger UI | http://localhost:8080/swagger-ui/index.html |
| RabbitMQ 관리 화면 | http://localhost:15672 (`.env`의 RABBITMQ_USER / PASSWORD) |
| PostgreSQL | localhost:5432 (`.env` 값) |

## 데이터 받기 (dump 복원)

dump 파일 이름은 `sona_YYYY-MM-DD.dump`(만든 날짜) 형식입니다.

1. 팀 드라이브에서 최신 dump(예: `sona_2026-11-24.dump`)를 받아 `dumps/`에 넣습니다.
2. 인프라가 떠 있는 상태에서 복원 스크립트를 실행합니다. 인자가 없으면 `dumps/`에서 **가장 최근에 수정된** `.dump` 파일을 복원하고, 시작 전에 어떤 파일인지 출력합니다. 특정 파일을 복원하려면 경로를 인자로 줍니다.

```powershell
# Windows PowerShell
.\scripts\db-restore.ps1                              # dumps/ 의 최신 .dump
.\scripts\db-restore.ps1 dumps\sona_2026-11-24.dump   # 파일 지정
```

```bash
# Mac
bash scripts/db-restore.sh                              # dumps/ 의 최신 .dump
bash scripts/db-restore.sh dumps/sona_2026-11-24.dump   # 파일 지정
```

> 받은 파일의 수정 시각이 다운로드 시각으로 바뀌므로, `dumps/`에 dump가 여러 개 있으면 파일을 지정하는 편이 안전합니다.

로컬에 PostgreSQL 클라이언트가 없어도 됩니다. 스크립트가 `docker` 명령으로 컨테이너 안의 도구를 사용합니다.

dump 만들기(데이터 담당자 전용): `db-dump.ps1` / `db-dump.sh`. 인자가 없으면 `dumps/sona_YYYY-MM-DD.dump`(오늘 날짜)로 저장하고, 경로를 인자로 주면 그 경로로 저장합니다(같은 이름이 있으면 덮어씁니다).

```powershell
.\scripts\db-dump.ps1                     # dumps/sona_<오늘>.dump
.\scripts\db-dump.ps1 dumps\test.dump     # 경로 지정
```

> PowerShell에서 스크립트 실행이 막히면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`를 한 번 실행하세요.

## 스키마가 바뀌었을 때

`infra/init.sql`은 **DB 볼륨이 처음 만들어질 때만** 실행됩니다. 스키마가 바뀌면 볼륨을 지우고 다시 만들어야 합니다.

```bash
git pull
docker compose -f infra/docker-compose.yml --env-file .env down -v   # -v: DB 데이터 삭제
docker compose -f infra/docker-compose.yml --env-file .env up -d
# 최신 dump(sona_YYYY-MM-DD.dump)를 dumps/에 넣고 restore 스크립트 실행
```

## 운영(prod) 설정

운영 서버(AWS)는 `prod` 프로필로 실행합니다. 로컬 개발에는 영향이 없습니다.

| 파일 | 용도 |
|---|---|
| `api-spring/src/main/resources/application-prod.yml` | 운영 설정. DB 접속 정보와 비밀값은 AWS Parameter Store(`/sona/prd/`)에서 읽어 옵니다 |
| `infra/prod/docker-compose.yml` | 운영 서버용 compose. postgres 없음(RDS 사용), ECR 이미지 사용, 8080만 노출 |

Parameter Store 키 (값은 AWS에만 저장, 커밋 금지):

| 키 | 유형 |
|---|---|
| `/sona/prd/spring.datasource.url` | String |
| `/sona/prd/spring.datasource.username` | String |
| `/sona/prd/spring.datasource.password` | SecureString |
| `/sona/prd/spring.rabbitmq.password` | SecureString |
| `/sona/prd/sona.embedding.api-key` | SecureString |
| `/sona/prd/sona.llm.provider` | String (`claude`. 없으면 `mock` = 가짜 응답) |
| `/sona/prd/sona.llm.api-key` | SecureString |

## 주의사항

- `.env`, 원본 데이터(`data/raw/`, hwp 등), dump 파일은 **절대 커밋하지 않습니다.** 이 레포는 public입니다.
- `spring.jpa.hibernate.ddl-auto`는 `validate`로 둡니다. `create`/`update`로 바꾸지 마세요. 스키마 변경은 `infra/init.sql`에서만 합니다.
