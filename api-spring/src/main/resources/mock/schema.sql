-- mock 프로필 전용 H2 스키마. infra/init.sql 의 서비스 테이블과 같은 내용 (분쟁사례 지식 테이블은 없음).
-- init.sql 을 바꾸면 여기도 같이 바꾼다.

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
    key_phrases              TEXT,                -- 정답을 담은 설명서 문구 (줄바꿈 구분). 3지선다 보기를 만들 때 함께 만든다
    status                   VARCHAR(20)  NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','SELECTED','APPROVED')),
    approved_at              TIMESTAMP,
    created_at               TIMESTAMP    NOT NULL DEFAULT now(),
    updated_at               TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE INDEX idx_questions_review ON questions (review_id, status);

-- 3지선다 보기 (spec 4.7.2). 정답 1 + 오해 2. 첫 실험 때 한 번 만들고 재실험에도 그대로 쓴다
CREATE TABLE question_options (
    id               BIGSERIAL PRIMARY KEY,
    question_id      BIGINT       NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    option_key       VARCHAR(1)   NOT NULL CHECK (option_key IN ('A','B','C')),
    option_text      TEXT         NOT NULL,
    is_correct       BOOLEAN      NOT NULL,
    is_critical      BOOLEAN      NOT NULL DEFAULT FALSE,   -- 실제보다 더 받는다고 믿는 오해
    created_at       TIMESTAMP    NOT NULL DEFAULT now(),
    UNIQUE (question_id, option_key)
);

CREATE TABLE question_evidences (
    id               BIGSERIAL PRIMARY KEY,
    question_id      BIGINT       NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    clause_id        BIGINT       REFERENCES clauses(id) ON DELETE CASCADE,
    case_chunk_id    BIGINT,  -- mock 에는 지식 테이블(case_chunk)이 없어 FK 없이 둔다
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
    prompt              TEXT         NOT NULL,
    -- 페르소나 속성 (spec 4.7.1). 실험에서 정보를 덜어 내는 규칙에 쓴다
    age_group           VARCHAR(10)  NOT NULL CHECK (age_group IN ('TWENTIES','FORTIES','SIXTIES')),
    diligence           NUMERIC(3,2) NOT NULL CHECK (diligence BETWEEN 0 AND 1),   -- 꼼꼼함
    info_path           VARCHAR(20)  NOT NULL CHECK (info_path IN ('GUIDE','AGENT_TALK')),  -- 설명서 직접 / 설계사 설명
    disposition         VARCHAR(20)  NOT NULL CHECK (disposition IN ('OPTIMISTIC','CAUTIOUS'))
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
    selected_option    VARCHAR(1)   CHECK (selected_option IN ('A','B','C')),   -- 3지선다로 고른 보기
    response_reason    TEXT,
    grading_result     VARCHAR(20)  CHECK (grading_result IN ('CORRECT','INCORRECT','UNDETERMINED')),
    evidence_page      INT,
    evidence_text      TEXT,
    created_at         TIMESTAMP    NOT NULL DEFAULT now(),
    UNIQUE (experiment_id, review_persona_id, question_id)
);

-- 읽기 메모 (spec 4.7.2): 페르소나가 설명서를 읽고 남긴 메모. 답할 때는 이 메모만 본다
CREATE TABLE reading_memos (
    id                 BIGSERIAL PRIMARY KEY,
    experiment_id      BIGINT       NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    review_persona_id  BIGINT       NOT NULL REFERENCES review_personas(id) ON DELETE CASCADE,
    memo               TEXT         NOT NULL,
    first_impression   TEXT,
    created_at         TIMESTAMP    NOT NULL DEFAULT now(),
    UNIQUE (experiment_id, review_persona_id)
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
