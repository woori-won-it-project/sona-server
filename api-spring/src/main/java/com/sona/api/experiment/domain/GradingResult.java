package com.sona.api.experiment.domain;

/** experiment_responses.grading_result: 정답 / 오답 / 판단 불가. 오해율 = (INCORRECT + UNDETERMINED) / 전체 */
public enum GradingResult {
    CORRECT,
    INCORRECT,
    UNDETERMINED
}
