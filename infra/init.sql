CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- 분쟁조정 자료 (사례 + 해결기준 + 결정례를 한 테이블에, doc_kind로 구분). 수집 이력은 data/raw/_report 리포트 JSON 으로 남긴다
CREATE TABLE dispute_case (
    id               BIGSERIAL PRIMARY KEY,
    doc_kind         VARCHAR(20)  NOT NULL,       -- CASE / STANDARD / DECISION (추후 PRECEDENT)
    source_url       VARCHAR(500) NOT NULL UNIQUE,
    source_key       VARCHAR(50),                 -- caseSlno / prcdntSlno
    category         VARCHAR(30),                 -- 보험 / 은행·중소서민 / 금융투자
    product_type     VARCHAR(100),                -- 상세의 '유형' (예: 실손보험(치료비), 자동차보험(대인))
    title            VARCHAR(500) NOT NULL,
    summary          TEXT,                        -- 해결기준의 '요지'
    complaint        TEXT,                        -- ▣ 민원내용
    dispute_issue    TEXT,                        -- ▣ 쟁점
    decision_reason  TEXT,                        -- ▣ 처리결과
    consumer_warning TEXT,                        -- ▣ 소비자 유의사항
    raw_text         TEXT,                        -- 파싱 전 본문 전체 (사례: HTML 본문 텍스트, 해결기준: hwp5txt 결과)
    raw_file_path    VARCHAR(500),                -- 원본 HTML 파일, data/raw/ 기준 상대경로 (나중에 S3 key로 교체)
    attachments      JSONB,                       -- 첨부파일 목록 [{name, url, local_path, size}]
    meta             JSONB,                       -- 화면에 있는 나머지 메타데이터 전부 (스키마 변경 없이 보관)
    registered_at    DATE,                        -- 게시일
    created_at       TIMESTAMP NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_dispute_case_kind_category ON dispute_case (doc_kind, category);

-- 검색 단위 청크 (임베딩은 여기서 관리. chunker.py 가 dispute_case 를 읽어 채움)
CREATE TABLE case_chunk (
    id               BIGSERIAL PRIMARY KEY,
    dispute_case_id  BIGINT NOT NULL REFERENCES dispute_case(id) ON DELETE CASCADE,
    chunk_type       VARCHAR(30)  NOT NULL CHECK (chunk_type IN ('CASE_BODY','STANDARD_SUMMARY','STANDARD_SECTION','BRIDGE',
                                                              'DECISION_SUMMARY','DECISION_FACTS','DECISION_JUDGMENT','DECISION_CLAUSE')),
    chunk_index      INT          NOT NULL DEFAULT 0,
    heading          VARCHAR(300),
    content          TEXT         NOT NULL,
    content_hash     CHAR(64)     NOT NULL,
    char_count       INT          NOT NULL,
    embedding        vector(1536),
    embedding_model  VARCHAR(100),
    created_at       TIMESTAMP    NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP    NOT NULL DEFAULT now(),
    UNIQUE (dispute_case_id, chunk_type, chunk_index)
);
CREATE INDEX idx_case_chunk_embedding ON case_chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_case_chunk_content_trgm ON case_chunk USING gin (content gin_trgm_ops);

-- 사례 태그 (상품·쟁점유형·개념·근거·결과 축)
CREATE TABLE case_tag (
    id               BIGSERIAL PRIMARY KEY,
    dispute_case_id  BIGINT NOT NULL REFERENCES dispute_case(id) ON DELETE CASCADE,
    axis             VARCHAR(30)  NOT NULL CHECK (axis IN ('PRODUCT','ISSUE_TYPE','CONCEPT','BASIS','OUTCOME')),
    value            VARCHAR(200) NOT NULL,
    source           VARCHAR(20)  NOT NULL CHECK (source IN ('FSS','LLM','MANUAL','RULE')),  -- RULE: 동의어 글자 일치 같은 규칙
    confidence       NUMERIC(3,2),
    created_at       TIMESTAMP    NOT NULL DEFAULT now(),
    UNIQUE (dispute_case_id, axis, value)
);
CREATE INDEX idx_case_tag_axis_value ON case_tag (axis, value);


-- =====================================================================
-- 서비스 테이블 (Spring 이 읽고 쓰는 테이블). 기준: ERD sona-v2 최종본, docs api.md v0.4
-- 검수(reviews)를 지우면 딸린 데이터가 모두 함께 지워진다 (하드 delete, ON DELETE CASCADE)
-- =====================================================================

CREATE TABLE members (
    id               BIGSERIAL PRIMARY KEY,
    employee_number  VARCHAR(30)  NOT NULL UNIQUE,
    name             VARCHAR(50)  NOT NULL,
    password_hash    VARCHAR(255) NOT NULL,       -- {bcrypt}... 처럼 해시 종류가 앞에 붙은 값
    created_at       TIMESTAMP    NOT NULL DEFAULT now()
);

CREATE TABLE reviews (
    id               BIGSERIAL PRIMARY KEY,
    member_id        BIGINT       NOT NULL REFERENCES members(id),
    title            VARCHAR(255),                -- 비면 첫 상품설명서 파일명
    status           VARCHAR(30)  NOT NULL DEFAULT 'IN_PROGRESS' CHECK (status IN ('IN_PROGRESS','COMPLETED')),
    current_step     VARCHAR(30)  NOT NULL DEFAULT 'DOC_UPLOAD'
                     CHECK (current_step IN ('DOC_UPLOAD','ANALYZING','QUESTION_SELECT','ANSWER_APPROVE',
                                             'PERSONA_SELECT','EXPERIMENT','REPORT','REVISION','REUPLOAD')),
    created_at       TIMESTAMP    NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP    NOT NULL DEFAULT now(),
    completed_at     TIMESTAMP
);
CREATE INDEX idx_reviews_member ON reviews (member_id, status);

CREATE TABLE documents (
    id                 BIGSERIAL PRIMARY KEY,
    review_id          BIGINT        NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    document_type      VARCHAR(30)   NOT NULL CHECK (document_type IN ('TERMS','PRODUCT_GUIDE','SPECIAL_TERMS')),
    version            BIGINT        NOT NULL DEFAULT 1,
    original_filename  VARCHAR(255)  NOT NULL,
    s3_path            VARCHAR(1024) NOT NULL,
    created_at         TIMESTAMP     NOT NULL DEFAULT now(),
    UNIQUE (review_id, document_type, version)
);

CREATE TABLE clauses (
    id               BIGSERIAL PRIMARY KEY,
    document_id      BIGINT       NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    clause_number    VARCHAR(50),                 -- 예: 제11조
    title            VARCHAR(255),
    content          TEXT         NOT NULL,
    start_page       INT          NOT NULL,
    end_page         INT          NOT NULL,
    sequence         INT          NOT NULL,       -- 문서 안 조항 순서
    created_at       TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE INDEX idx_clauses_document ON clauses (document_id, sequence);

CREATE TABLE questions (
    id                       BIGSERIAL PRIMARY KEY,
    review_id                BIGINT       NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    title                    VARCHAR(100),        -- 질문 짧은 제목 (현재 API 미노출)
    source_type              VARCHAR(30)  NOT NULL CHECK (source_type IN ('CASE_BASED','MISUNDERSTANDING','MANUAL')),
    question_text            TEXT         NOT NULL,
    generation_reason        TEXT,
    reference_answer         VARCHAR(10)  CHECK (reference_answer IN ('YES','NO')),
    reference_answer_reason  TEXT,
    status                   VARCHAR(20)  NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','SELECTED','APPROVED')),
    approved_at              TIMESTAMP,
    created_at               TIMESTAMP    NOT NULL DEFAULT now(),
    updated_at               TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE INDEX idx_questions_review ON questions (review_id, status);

CREATE TABLE question_evidences (
    id               BIGSERIAL PRIMARY KEY,
    question_id      BIGINT       NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    clause_id        BIGINT       REFERENCES clauses(id) ON DELETE CASCADE,
    case_chunk_id    BIGINT       REFERENCES case_chunk(id) ON DELETE SET NULL,  -- 지식 테이블: 재청킹돼도 근거는 남김
    source_page      INT,
    evidence_text    TEXT         NOT NULL,
    created_at       TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE INDEX idx_question_evidences_question ON question_evidences (question_id);

CREATE TABLE personas (
    id                  BIGSERIAL PRIMARY KEY,
    name                VARCHAR(100) NOT NULL,
    financial_literacy  VARCHAR(20)  NOT NULL CHECK (financial_literacy IN ('LOW','MEDIUM','HIGH')),
    reading_behavior    TEXT         NOT NULL,
    description         TEXT,
    prompt              TEXT         NOT NULL
);

CREATE TABLE review_personas (
    id               BIGSERIAL PRIMARY KEY,
    review_id        BIGINT       NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    persona_id       BIGINT       NOT NULL REFERENCES personas(id),
    UNIQUE (review_id, persona_id)
);

CREATE TABLE experiments (
    id                    BIGSERIAL PRIMARY KEY,
    review_id             BIGINT       NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    parent_experiment_id  BIGINT       REFERENCES experiments(id) ON DELETE CASCADE,  -- null 이면 첫 실험
    round_number          INT          NOT NULL DEFAULT 1,
    status                VARCHAR(30)  NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
    created_at            TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE INDEX idx_experiments_review ON experiments (review_id, status);

CREATE TABLE experiment_documents (
    id               BIGSERIAL PRIMARY KEY,
    experiment_id    BIGINT       NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    document_id      BIGINT       NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    UNIQUE (experiment_id, document_id)
);

CREATE TABLE experiment_responses (
    id                 BIGSERIAL PRIMARY KEY,
    experiment_id      BIGINT       NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    review_persona_id  BIGINT       NOT NULL REFERENCES review_personas(id) ON DELETE CASCADE,
    document_id        BIGINT       NOT NULL REFERENCES documents(id) ON DELETE CASCADE,  -- 응답 근거 문서
    question_id        BIGINT       NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    selected_answer    VARCHAR(10)  CHECK (selected_answer IN ('YES','NO','UNSURE')),
    response_reason    TEXT,
    grading_result     VARCHAR(20)  CHECK (grading_result IN ('CORRECT','INCORRECT','UNDETERMINED')),
    evidence_page      INT,
    evidence_text      TEXT,
    created_at         TIMESTAMP    NOT NULL DEFAULT now(),
    UNIQUE (experiment_id, review_persona_id, question_id)
);

CREATE TABLE revision_suggestions (
    id               BIGSERIAL PRIMARY KEY,
    document_id      BIGINT       NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    question_id      BIGINT       NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    experiment_id    BIGINT       NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    source_page      INT,
    original_text    TEXT         NOT NULL,
    suggested_text   TEXT         NOT NULL,
    revision_reason  TEXT         NOT NULL,
    created_at       TIMESTAMP    NOT NULL DEFAULT now(),
    UNIQUE (experiment_id, question_id)
);
