package com.sona.api.global.response;

/**
 * 돌려줄 데이터가 없는 응답 (삭제, 로그아웃 등). {@code {"message": "..."}}
 */
public record MessageResponse(String message) {

    public static MessageResponse of(String message) {
        return new MessageResponse(message);
    }
}
