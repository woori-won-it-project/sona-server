package com.sona.api.global.auth;

import java.util.Optional;
import org.springframework.stereotype.Component;

/**
 * 임시 토큰: "mock-{회원ID}". 서명이 없어 위조가 쉬우므로 실제 배포 전에 JWT 구현으로 교체한다.
 */
@Component
public class MockTokenProvider implements TokenProvider {

    private static final String PREFIX = "mock-";

    @Override
    public String issue(Long memberId) {
        return PREFIX + memberId;
    }

    @Override
    public Optional<Long> parseMemberId(String token) {
        if (token == null || !token.startsWith(PREFIX)) {
            return Optional.empty();
        }
        try {
            return Optional.of(Long.parseLong(token.substring(PREFIX.length())));
        } catch (NumberFormatException e) {
            return Optional.empty();
        }
    }

    @Override
    public long expiresInSeconds() {
        return 3600;
    }
}
