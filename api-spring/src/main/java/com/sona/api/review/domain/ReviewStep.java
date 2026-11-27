package com.sona.api.review.domain;

/** reviews.current_step: 지금 단계 (api.md 13장). ANALYZING, EXPERIMENT 는 처리 중 표시와 중복 실행 방지용 */
public enum ReviewStep {
    DOC_UPLOAD,
    ANALYZING,
    QUESTION_SELECT,
    ANSWER_APPROVE,
    PERSONA_SELECT,
    EXPERIMENT,
    REPORT,
    REVISION,
    REUPLOAD
}
