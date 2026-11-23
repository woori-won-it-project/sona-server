CREATE EXTENSION IF NOT EXISTS vector;

-- 수집 작업 이력
CREATE TABLE crawl_job (
    id            BIGSERIAL PRIMARY KEY,
    source        VARCHAR(30)  NOT NULL,          -- CASE / STANDARD
    status        VARCHAR(20)  NOT NULL,          -- RUNNING / SUCCESS / FAILED
    total_count   INT          NOT NULL DEFAULT 0,
    success_count INT          NOT NULL DEFAULT 0,
    fail_count    INT          NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at    TIMESTAMP    NOT NULL DEFAULT now(),
    finished_at   TIMESTAMP
);

-- 분쟁조정 자료 (사례 + 해결기준을 한 테이블에, doc_kind로 구분)
CREATE TABLE dispute_case (
    id               BIGSERIAL PRIMARY KEY,
    crawl_job_id     BIGINT REFERENCES crawl_job(id),
    doc_kind         VARCHAR(20)  NOT NULL,       -- CASE / STANDARD (추후 DECISION, PRECEDENT)
    source_url       VARCHAR(500) NOT NULL UNIQUE,
    source_key       VARCHAR(50),                 -- caseSlno / prcdntSlno
    category         VARCHAR(30),                 -- 보험 / 은행·중소서민 / 금융투자
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
    embedding        vector(1536),                -- 임베딩 모델 확정 전까지 NULL. 차원은 모델에 따라 변경
    created_at       TIMESTAMP NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_dispute_case_kind_category ON dispute_case (doc_kind, category);
