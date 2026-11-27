package com.sona.api.global.error;

import java.util.Map;

/**
 * 에러 응답 공통 틀 (api.md 0.2). {@code details} 는 없으면 {@code null}.
 */
public record ErrorResponse(String code, String message, Map<String, Object> details) {

    public static ErrorResponse of(ErrorCode errorCode) {
        return new ErrorResponse(errorCode.name(), errorCode.getMessage(), null);
    }

    public static ErrorResponse of(ErrorCode errorCode, Map<String, Object> details) {
        return new ErrorResponse(errorCode.name(), errorCode.getMessage(), details);
    }
}
