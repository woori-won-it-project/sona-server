package com.sona.api.global.error;

import java.util.Map;
import lombok.Getter;

/**
 * 서비스 규칙 위반을 알릴 때 던지는 예외. {@link GlobalExceptionHandler} 가 에러 응답으로 바꾼다.
 *
 * <pre>
 * throw new BusinessException(ErrorCode.REVIEW_LOCKED);
 * throw new BusinessException(ErrorCode.QUESTION_NOT_APPROVED, Map.of("questionIds", List.of(12, 15)));
 * </pre>
 */
@Getter
public class BusinessException extends RuntimeException {

    private final ErrorCode errorCode;
    private final Map<String, Object> details;

    public BusinessException(ErrorCode errorCode) {
        this(errorCode, null);
    }

    public BusinessException(ErrorCode errorCode, Map<String, Object> details) {
        super(errorCode.getMessage());
        this.errorCode = errorCode;
        this.details = details;
    }
}
