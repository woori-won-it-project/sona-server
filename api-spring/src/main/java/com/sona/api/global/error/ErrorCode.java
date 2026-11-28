package com.sona.api.global.error;

import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;

/**
 * 에러 코드 목록 (api.md 12장). 프론트는 code 로 분기하고, message 는 화면에 그대로 띄워도 된다.
 */
@Getter
@RequiredArgsConstructor
public enum ErrorCode {

    // 공통
    INVALID_INPUT(HttpStatus.BAD_REQUEST, "입력값을 확인해 주세요."),
    UNAUTHORIZED(HttpStatus.UNAUTHORIZED, "로그인 정보가 유효하지 않거나 만료되었습니다."),
    NOT_FOUND(HttpStatus.NOT_FOUND, "요청한 자원을 찾을 수 없습니다."),
    INTERNAL_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."),
    AI_CALL_FAILED(HttpStatus.BAD_GATEWAY, "AI 처리 중 오류가 발생했습니다. 다시 시도해 주세요."),

    // 로그인
    LOGIN_FAILED(HttpStatus.UNAUTHORIZED, "사번 또는 비밀번호가 올바르지 않습니다."),
    INVALID_CSRF_TOKEN(HttpStatus.FORBIDDEN, "CSRF Token이 유효하지 않습니다."),

    // 검수 상태
    INVALID_REVIEW_STATUS(HttpStatus.CONFLICT, "지금 단계에서는 할 수 없는 작업입니다."),
    REVIEW_PROCESSING(HttpStatus.CONFLICT, "분석 또는 실험이 진행 중입니다. 끝난 뒤 다시 시도해 주세요."),
    REVIEW_LOCKED(HttpStatus.CONFLICT, "첫 실험 이후에는 질문, 기준답안, 페르소나를 바꿀 수 없습니다."),

    // 문서
    FILE_TOO_LARGE(HttpStatus.PAYLOAD_TOO_LARGE, "파일은 20MB 이하만 올릴 수 있습니다."),
    INVALID_FILE_TYPE(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "PDF 파일만 올릴 수 있습니다."),
    ONLY_PRODUCT_GUIDE_ALLOWED(HttpStatus.CONFLICT, "첫 실험 이후에는 상품설명서만 다시 올릴 수 있습니다."),
    REQUIRED_DOCUMENT_MISSING(HttpStatus.CONFLICT, "보험약관과 상품설명서를 모두 올려 주세요."),

    // 질문 · 기준답안
    INVALID_QUESTION_STATUS(HttpStatus.CONFLICT, "선택된 질문만 기준답안을 수정할 수 있습니다."),
    REFERENCE_ANSWER_EMPTY(HttpStatus.CONFLICT, "답안을 선택한 뒤 승인해 주세요."),
    QUESTION_NOT_APPROVED(HttpStatus.CONFLICT, "아직 승인하지 않은 질문이 있어요."),

    // 페르소나 · 실험
    PERSONA_NOT_SELECTED(HttpStatus.CONFLICT, "실험에 참여할 페르소나를 선택해 주세요."),
    INITIAL_EXPERIMENT_EXISTS(HttpStatus.CONFLICT, "첫 실험은 이미 진행했습니다."),
    NEW_DOCUMENT_REQUIRED(HttpStatus.CONFLICT, "재실험하려면 수정한 상품설명서를 먼저 올려 주세요."),
    INVALID_PARENT_EXPERIMENT(HttpStatus.CONFLICT, "비교 기준이 될 실험이 올바르지 않습니다."),

    // 리포트 · 수정 제안 · 비교
    SUGGESTION_ALREADY_EXISTS(HttpStatus.CONFLICT, "이 질문의 수정 제안이 이미 있습니다."),
    COMPARISON_NOT_AVAILABLE(HttpStatus.CONFLICT, "재실험 결과가 있어야 비교할 수 있습니다.");

    private final HttpStatus status;
    private final String message;
}
