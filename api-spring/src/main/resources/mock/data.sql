-- mock 프로필 목업 데이터. 모두 지어낸 테스트 값이다 (실제 상품·회원 아님).
-- 로그인: 사번 EMP001 / 비밀번호 password123
--
-- 검수 1: 첫 실험 -> 수정 제안 -> 상품설명서 V2 업로드 -> 재실험까지 끝난 상태 (리포트·비교 화면 시험용)
--   첫 실험 오해율: (오답 1 + 판단 불가 2) / 9 = 33.33
--   재실험 오해율: (오답 0 + 판단 불가 1) / 9 = 11.11
-- 검수 2: 문서 등록 단계 (홈 목록 시험용)
-- 검수 3: 질문 승인까지 끝나고 페르소나 선택 전 (페르소나 실험 시험용, 상품설명서 조항 5개)

-- 회원 ------------------------------------------------------------------
INSERT INTO members (id, employee_number, name, password_hash, created_at) VALUES
(1, 'EMP001', '홍길동', '{noop}password123', TIMESTAMP '2026-11-20 09:00:00'),
(2, 'EMP002', '김테스트', '{noop}password123', TIMESTAMP '2026-11-20 09:00:00');

-- 검수 ------------------------------------------------------------------
INSERT INTO reviews (id, member_id, title, status, current_step, created_at, updated_at, completed_at) VALUES
(1, 1, '암치료보험_상품설명서', 'IN_PROGRESS', 'REPORT', TIMESTAMP '2026-11-25 10:00:00', TIMESTAMP '2026-11-25 15:10:00', NULL),
(2, 1, '실손보험_상품설명서', 'IN_PROGRESS', 'DOC_UPLOAD', TIMESTAMP '2026-11-25 16:00:00', TIMESTAMP '2026-11-25 16:00:00', NULL),
(3, 1, '연습용_암보험_상품설명서', 'IN_PROGRESS', 'PERSONA_SELECT', TIMESTAMP '2026-11-26 09:00:00', TIMESTAMP '2026-11-26 09:30:00', NULL);

-- 문서 (검수 1: 약관, 상품설명서 V1, 특약, 상품설명서 V2 / 검수 2: 약관) ----------
INSERT INTO documents (id, review_id, document_type, version, original_filename, s3_path, created_at) VALUES
(1, 1, 'TERMS', 1, '암치료보험_약관.pdf', 'mock/reviews/1/terms_v1.pdf', TIMESTAMP '2026-11-25 10:01:00'),
(2, 1, 'PRODUCT_GUIDE', 1, '암치료보험_상품설명서.pdf', 'mock/reviews/1/guide_v1.pdf', TIMESTAMP '2026-11-25 10:01:00'),
(3, 1, 'SPECIAL_TERMS', 1, '암치료보험_특약.pdf', 'mock/reviews/1/special_v1.pdf', TIMESTAMP '2026-11-25 10:02:00'),
(4, 1, 'PRODUCT_GUIDE', 2, '암치료보험_상품설명서_v2.pdf', 'mock/reviews/1/guide_v2.pdf', TIMESTAMP '2026-11-25 14:00:00'),
(5, 2, 'TERMS', 1, '실손보험_약관.pdf', 'mock/reviews/2/terms_v1.pdf', TIMESTAMP '2026-11-25 16:01:00'),
(6, 3, 'TERMS', 1, '연습용_암보험_약관.pdf', 'mock/reviews/3/terms_v1.pdf', TIMESTAMP '2026-11-26 09:01:00'),
(7, 3, 'PRODUCT_GUIDE', 1, '연습용_암보험_상품설명서.pdf', 'mock/reviews/3/guide_v1.pdf', TIMESTAMP '2026-11-26 09:01:00');

-- 조항 (검수 1 약관) ----------------------------------------------------
INSERT INTO clauses (id, document_id, clause_number, title, content, start_page, end_page, sequence, created_at) VALUES
(1, 1, '제7조', '암 주요치료의 제외', '면역력 강화 치료는 암 주요치료에 포함되지 않습니다.', 29, 29, 1, TIMESTAMP '2026-11-25 10:05:00'),
(2, 1, '제9조', '항암중입자치료의 정의', '항암양성자방사선치료는 항암중입자치료에 포함하지 않습니다.', 30, 30, 2, TIMESTAMP '2026-11-25 10:05:00'),
(3, 1, '제11조', '암주요치료비 지급사유', '암 진단확정 후 지급기간 내 암 주요치료를 받은 경우 지급합니다.', 32, 32, 3, TIMESTAMP '2026-11-25 10:05:00'),
-- 검수 3 상품설명서 (지어낸 문구) : 페르소나가 읽는 글
(4, 7, NULL, '상품 개요', '이 보험은 암 진단확정 후 암 주요치료를 받으면 치료비를 드리는 갱신형 보험입니다. 보험기간은 10년이며 갱신할 수 있습니다.', 2, 2, 1, TIMESTAMP '2026-11-26 09:05:00'),
(5, 7, NULL, '보장 내용', '암 주요치료비는 연간 1회, 최대 10회까지 1,000만원을 지급합니다. 다만 가입 후 1년이 지나기 전에 지급사유가 생기면 50%인 500만원을 지급합니다.', 3, 3, 2, TIMESTAMP '2026-11-26 09:05:00'),
(6, 7, NULL, '보장하지 않는 치료', '호르몬 관련 치료제를 쓰는 치료는 암 주요치료에서 제외합니다. 암의 합병증이나 후유증을 치료하는 경우도 보장하지 않습니다.', 3, 3, 3, TIMESTAMP '2026-11-26 09:05:00'),
(7, 7, NULL, '갱신', '갱신할 때 나이가 늘고 보험요율이 바뀌어 보험료가 인상될 수 있습니다.', 4, 4, 4, TIMESTAMP '2026-11-26 09:05:00'),
(8, 7, NULL, '해약환급금', '이 보험은 해약환급금이 없거나 납입한 보험료보다 적을 수 있습니다.', 4, 4, 5, TIMESTAMP '2026-11-26 09:05:00');

-- 질문 (1~3 승인, 4 는 선택 안 함) ---------------------------------------
INSERT INTO questions (id, review_id, title, source_type, question_text, generation_reason, reference_answer, reference_answer_reason, status, approved_at, created_at, updated_at) VALUES
(1, 1, '암주요치료비 지급 조건', 'CASE_BASED', '암 진단만으로 암주요치료비를 받을 수 있나요?', '암 진단만으로 보험금이 지급된다고 이해할 가능성이 있어 지급 조건을 점검해요.', 'NO', '아니요. 진단 후 약관에서 정한 암 주요치료를 받아야 지급돼요.', 'APPROVED', TIMESTAMP '2026-11-25 11:30:00', TIMESTAMP '2026-11-25 10:06:00', TIMESTAMP '2026-11-25 11:30:00'),
(2, 1, '면역력 강화 치료의 제외', 'MISUNDERSTANDING', '면역력 강화 치료는 암 주요치료에서 제외되나요?', '치료라는 표현만 보고 제외 규정을 놓칠 수 있어요.', 'YES', '예. 면역력 강화 치료는 암 주요치료에서 제외돼요.', 'APPROVED', TIMESTAMP '2026-11-25 11:31:00', TIMESTAMP '2026-11-25 10:06:00', TIMESTAMP '2026-11-25 11:31:00'),
(3, 1, NULL, 'MANUAL', '양성자치료도 항암중입자치료에 포함되나요?', NULL, 'NO', '아니요. 양성자치료는 항암중입자치료에 포함하지 않아요.', 'APPROVED', TIMESTAMP '2026-11-25 11:32:00', TIMESTAMP '2026-11-25 10:30:00', TIMESTAMP '2026-11-25 11:32:00'),
(4, 1, '최초 진단확정일', 'CASE_BASED', '다른 암을 나중에 진단받으면 지급기간이 새로 시작되나요?', '지급기간 기산점을 오해한 분쟁사례가 있어요.', NULL, NULL, 'DRAFT', NULL, TIMESTAMP '2026-11-25 10:06:00', TIMESTAMP '2026-11-25 10:06:00'),
-- 검수 3 질문 (모두 승인)
(5, 3, '1년 내 감액', 'CASE_BASED', '가입 후 6개월 만에 암 주요치료를 받으면 1,000만원을 모두 받나요?', '가입 초기 감액을 놓친 분쟁사례가 있어요.', 'NO', '아니요. 가입 후 1년이 지나기 전이면 50%인 500만원만 받아요.', 'APPROVED', TIMESTAMP '2026-11-26 09:20:00', TIMESTAMP '2026-11-26 09:10:00', TIMESTAMP '2026-11-26 09:20:00'),
(6, 3, '호르몬 치료 제외', 'MISUNDERSTANDING', '호르몬 치료제로 암을 치료해도 암 주요치료비를 받나요?', '치료라는 말만 보고 제외 항목을 놓칠 수 있어요.', 'NO', '아니요. 호르몬 관련 치료제를 쓰는 치료는 제외돼요.', 'APPROVED', TIMESTAMP '2026-11-26 09:21:00', TIMESTAMP '2026-11-26 09:10:00', TIMESTAMP '2026-11-26 09:21:00'),
(7, 3, '갱신 보험료', 'CASE_BASED', '갱신할 때 보험료가 오를 수 있나요?', '갱신 보험료가 그대로라고 오해한 분쟁사례가 있어요.', 'YES', '예. 나이와 보험요율에 따라 오를 수 있어요.', 'APPROVED', TIMESTAMP '2026-11-26 09:22:00', TIMESTAMP '2026-11-26 09:10:00', TIMESTAMP '2026-11-26 09:22:00');

-- 질문 근거 (분쟁사례 청크는 mock 에 없어서 case_chunk_id 는 비워 둠) ---------
INSERT INTO question_evidences (id, question_id, clause_id, case_chunk_id, source_page, evidence_text, created_at) VALUES
(1, 1, 3, NULL, 32, '암 진단확정 후 지급기간 내 암 주요치료를 받은 경우 지급합니다.', TIMESTAMP '2026-11-25 10:06:00'),
(2, 2, 1, NULL, 29, '면역력 강화 치료는 암 주요치료에 포함되지 않습니다.', TIMESTAMP '2026-11-25 10:06:00'),
(3, 3, 2, NULL, 30, '항암양성자방사선치료는 항암중입자치료에 포함하지 않습니다.', TIMESTAMP '2026-11-25 10:31:00'),
(4, 4, NULL, NULL, NULL, '가장 먼저 암으로 진단확정된 날을 최초 암진단확정일로 봅니다.', TIMESTAMP '2026-11-25 10:06:00');

-- 페르소나 10명 (이름은 Figma 와이어프레임 2차 기준, 속성 값은 spec 4.7.1 에 맞춘 임시 배정) ----------
-- 꼼꼼함은 나이대 기준값(20대 0.47, 40대 0.60, 60대 0.46) 근처로 흩어 둠
INSERT INTO personas (id, name, financial_literacy, reading_behavior, description, prompt, age_group, diligence, info_path, disposition) VALUES
(1, '보장 요약형', 'LOW', '요약 설명만 읽음', '주요 보장 내용 위주로 확인하는 소비자', '당신은 금융 지식이 적고 상품설명서의 요약 부분만 읽는 소비자입니다.', 'SIXTIES', 0.40, 'AGENT_TALK', 'OPTIMISTIC'),
(2, '금액 우선형', 'LOW', '보험료와 보장금액부터 확인', '숫자 위주로 읽는 소비자', '당신은 보험료와 보장금액 숫자부터 확인하는 소비자입니다.', 'TWENTIES', 0.40, 'GUIDE', 'OPTIMISTIC'),
(3, '예시 참고형', 'LOW', '가입 예시를 먼저 읽음', '예시 표를 기준으로 이해하는 소비자', '당신은 가입 예시를 먼저 읽고 그 기준으로 이해하는 소비자입니다.', 'SIXTIES', 0.45, 'GUIDE', 'CAUTIOUS'),
(4, '용어 확인형', 'LOW', '낯선 용어의 정의를 찾아봄', '모르는 용어가 나오면 정의를 찾는 소비자', '당신은 낯선 용어가 나오면 정의를 찾아 읽는 소비자입니다.', 'TWENTIES', 0.55, 'GUIDE', 'CAUTIOUS'),
(5, '경험 대조형', 'MEDIUM', '기존 계약 경험과 비교', '과거 청구 경험으로 해석하는 소비자', '당신은 예전 보험 계약과 청구 경험에 비추어 해석하는 소비자입니다.', 'FORTIES', 0.55, 'AGENT_TALK', 'OPTIMISTIC'),
(6, '조건 탐색형', 'MEDIUM', '지급 조건 키워드를 검색', '지급 조건과 예외사항을 찾아보는 소비자', '당신은 지급 조건 관련 키워드를 찾아 읽는 소비자입니다.', 'FORTIES', 0.65, 'GUIDE', 'CAUTIOUS'),
(7, '요약 대조형', 'MEDIUM', '요약과 관련 조항을 대조', '요약과 조항을 맞춰 보는 소비자', '당신은 요약 설명과 관련 조항을 대조해 읽는 소비자입니다.', 'SIXTIES', 0.50, 'GUIDE', 'OPTIMISTIC'),
(8, '수치 비교형', 'HIGH', '보장 한도와 기간부터 비교', '한도와 기간을 꼼꼼히 비교하는 소비자', '당신은 금융 지식이 높고 보장 한도와 기간을 비교하는 소비자입니다.', 'FORTIES', 0.65, 'GUIDE', 'OPTIMISTIC'),
(9, '예외 점검형', 'HIGH', '면책·제외 조건부터 확인', '예외와 제한 조건을 먼저 보는 소비자', '당신은 면책과 제외 조건부터 확인하는 소비자입니다.', 'TWENTIES', 0.60, 'GUIDE', 'CAUTIOUS'),
(10, '약관 정독형', 'HIGH', '참조 조항과 특약까지 정독', '예외와 제한 조건까지 꼼꼼히 확인하는 소비자', '당신은 참조 조항과 특약까지 정독하는 소비자입니다.', 'FORTIES', 0.75, 'GUIDE', 'CAUTIOUS');

-- 검수 1 에서 고른 페르소나: 보장 요약형(1), 조건 탐색형(6), 약관 정독형(10) ----------
INSERT INTO review_personas (id, review_id, persona_id) VALUES
(1, 1, 1),
(2, 1, 6),
(3, 1, 10);

-- 실험 (1: 첫 실험 V1, 2: 재실험 V2) --------------------------------------
INSERT INTO experiments (id, review_id, parent_experiment_id, round_number, status, created_at) VALUES
(1, 1, NULL, 1, 'COMPLETED', TIMESTAMP '2026-11-25 12:00:00'),
(2, 1, 1, 2, 'COMPLETED', TIMESTAMP '2026-11-25 15:00:00');

INSERT INTO experiment_documents (id, experiment_id, document_id) VALUES
(1, 1, 1), (2, 1, 2), (3, 1, 3),
(4, 2, 1), (5, 2, 4), (6, 2, 3);

-- 실험 응답: 실험 1 (상품설명서 V1 = 문서 2) ----------------------------------
-- 질문 1: 오답 1, 판단 불가 1, 정답 1 -> 66.67 (수정 필요) / 질문 2: 모두 정답 / 질문 3: 판단 불가 1
INSERT INTO experiment_responses (id, experiment_id, review_persona_id, document_id, question_id, selected_answer, response_reason, grading_result, evidence_page, evidence_text, created_at) VALUES
(1, 1, 1, 2, 1, 'YES', '암 진단을 받으면 지급된다고 적혀 있어 그렇게 판단했습니다.', 'INCORRECT', 20, '암주요치료비 1,000만원(1구좌 기준, 연 1회·최대 10년).', TIMESTAMP '2026-11-25 12:01:00'),
(2, 1, 2, 2, 1, 'UNSURE', '지급 조건이 진단인지 치료인지 설명서만으로는 알 수 없었습니다.', 'UNDETERMINED', 20, '암주요치료비 1,000만원(1구좌 기준, 연 1회·최대 10년).', TIMESTAMP '2026-11-25 12:01:00'),
(3, 1, 3, 2, 1, 'NO', '주요치료를 받아야 지급된다는 조건을 확인했습니다.', 'CORRECT', 21, '암 주요치료를 받은 경우 지급합니다.', TIMESTAMP '2026-11-25 12:01:00'),
(4, 1, 1, 2, 2, 'YES', '제외 항목에 면역력 강화 치료가 있었습니다.', 'CORRECT', 22, '면역력 강화 치료는 보장하지 않습니다.', TIMESTAMP '2026-11-25 12:02:00'),
(5, 1, 2, 2, 2, 'YES', '제외 조건 키워드로 확인했습니다.', 'CORRECT', 22, '면역력 강화 치료는 보장하지 않습니다.', TIMESTAMP '2026-11-25 12:02:00'),
(6, 1, 3, 2, 2, 'YES', '약관 제7조의 제외 항목과 일치합니다.', 'CORRECT', 22, '면역력 강화 치료는 보장하지 않습니다.', TIMESTAMP '2026-11-25 12:02:00'),
(7, 1, 1, 2, 3, 'UNSURE', '양성자치료에 대한 설명을 찾지 못했습니다.', 'UNDETERMINED', NULL, NULL, TIMESTAMP '2026-11-25 12:03:00'),
(8, 1, 2, 2, 3, 'NO', '중입자치료 정의에 양성자치료는 없었습니다.', 'CORRECT', 23, '항암중입자치료는 탄소이온을 이용한 치료를 말합니다.', TIMESTAMP '2026-11-25 12:03:00'),
(9, 1, 3, 2, 3, 'NO', '약관 제9조에 양성자치료는 포함하지 않는다고 되어 있습니다.', 'CORRECT', 23, '항암중입자치료는 탄소이온을 이용한 치료를 말합니다.', TIMESTAMP '2026-11-25 12:03:00');

-- 실험 응답: 실험 2 (상품설명서 V2 = 문서 4) ----------------------------------
INSERT INTO experiment_responses (id, experiment_id, review_persona_id, document_id, question_id, selected_answer, response_reason, grading_result, evidence_page, evidence_text, created_at) VALUES
(10, 2, 1, 4, 1, 'NO', '진단확정 후 주요치료 시 지급한다고 바뀌어 있었습니다.', 'CORRECT', 20, '암 진단확정 후 10년 내 주요치료 시 연 1회 지급합니다.', TIMESTAMP '2026-11-25 15:01:00'),
(11, 2, 2, 4, 1, 'NO', '주요치료 조건이 명확히 보였습니다.', 'CORRECT', 20, '암 진단확정 후 10년 내 주요치료 시 연 1회 지급합니다.', TIMESTAMP '2026-11-25 15:01:00'),
(12, 2, 3, 4, 1, 'NO', '주요치료를 받아야 지급됩니다.', 'CORRECT', 20, '암 진단확정 후 10년 내 주요치료 시 연 1회 지급합니다.', TIMESTAMP '2026-11-25 15:01:00'),
(13, 2, 1, 4, 2, 'YES', '제외 항목에 면역력 강화 치료가 있었습니다.', 'CORRECT', 22, '면역력 강화 치료는 보장하지 않습니다.', TIMESTAMP '2026-11-25 15:02:00'),
(14, 2, 2, 4, 2, 'YES', '제외 조건을 확인했습니다.', 'CORRECT', 22, '면역력 강화 치료는 보장하지 않습니다.', TIMESTAMP '2026-11-25 15:02:00'),
(15, 2, 3, 4, 2, 'YES', '약관과 일치합니다.', 'CORRECT', 22, '면역력 강화 치료는 보장하지 않습니다.', TIMESTAMP '2026-11-25 15:02:00'),
(16, 2, 1, 4, 3, 'UNSURE', '양성자치료에 대한 설명을 찾지 못했습니다.', 'UNDETERMINED', NULL, NULL, TIMESTAMP '2026-11-25 15:03:00'),
(17, 2, 2, 4, 3, 'NO', '중입자치료 정의에 양성자치료는 없었습니다.', 'CORRECT', 23, '항암중입자치료는 탄소이온을 이용한 치료를 말합니다.', TIMESTAMP '2026-11-25 15:03:00'),
(18, 2, 3, 4, 3, 'NO', '양성자치료는 포함하지 않습니다.', 'CORRECT', 23, '항암중입자치료는 탄소이온을 이용한 치료를 말합니다.', TIMESTAMP '2026-11-25 15:03:00');

-- 수정 제안 (실험 1, 질문 1, 상품설명서 V1) ---------------------------------
INSERT INTO revision_suggestions (id, document_id, question_id, experiment_id, source_page, original_text, suggested_text, revision_reason, created_at) VALUES
(1, 2, 1, 1, 20, '암주요치료비 1,000만원(1구좌 기준, 연 1회·최대 10년).', '암보장개시일 이후 암 진단확정 후 10년 내 주요치료 시 연 1회(최대 10회) 지급합니다.', '암 진단만으로 지급된다는 오답이 나왔습니다. 진단확정, 주요치료 시행, 지급기간을 순서대로 밝혔습니다.', TIMESTAMP '2026-11-25 13:00:00');

-- 직접 넣은 id 다음 번호부터 새 행이 생기도록 자동 번호를 뒤로 민다 ----------------
ALTER TABLE members ALTER COLUMN id RESTART WITH 100;
ALTER TABLE reviews ALTER COLUMN id RESTART WITH 100;
ALTER TABLE documents ALTER COLUMN id RESTART WITH 100;
ALTER TABLE clauses ALTER COLUMN id RESTART WITH 100;
ALTER TABLE questions ALTER COLUMN id RESTART WITH 100;
ALTER TABLE question_options ALTER COLUMN id RESTART WITH 100;
ALTER TABLE question_evidences ALTER COLUMN id RESTART WITH 100;
ALTER TABLE personas ALTER COLUMN id RESTART WITH 100;
ALTER TABLE review_personas ALTER COLUMN id RESTART WITH 100;
ALTER TABLE experiments ALTER COLUMN id RESTART WITH 100;
ALTER TABLE experiment_documents ALTER COLUMN id RESTART WITH 100;
ALTER TABLE experiment_responses ALTER COLUMN id RESTART WITH 100;
ALTER TABLE reading_memos ALTER COLUMN id RESTART WITH 100;
ALTER TABLE revision_suggestions ALTER COLUMN id RESTART WITH 100;
