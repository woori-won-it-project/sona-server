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

