package com.sona.api.global.auth;

import java.util.Optional;

/**
 * 토큰 발급과 해석. 지금은 MockTokenProvider 하나뿐이고, JWT 구현으로 바꿔 끼우면 나머지 코드는 그대로 쓴다.
 */
public interface TokenProvider {

    String issue(Long memberId);

    /** 토큰이 올바르면 회원 ID, 아니면 empty. */
    Optional<Long> parseMemberId(String token);

    long expiresInSeconds();
}
