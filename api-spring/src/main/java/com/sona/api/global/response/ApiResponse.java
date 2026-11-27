package com.sona.api.global.response;

/**
 * 성공 응답 공통 틀. 모든 성공 응답은 {@code {"data": ...}} 모양으로 보낸다 (api.md 0.1).
 */
public record ApiResponse<T>(T data) {

    public static <T> ApiResponse<T> of(T data) {
        return new ApiResponse<>(data);
    }
}
