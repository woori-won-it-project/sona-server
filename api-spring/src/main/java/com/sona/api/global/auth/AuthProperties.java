package com.sona.api.global.auth;

import java.time.Duration;

public record AuthProperties(String issuer, String audience) {

    static final Duration ACCESS_LIFETIME = Duration.ofMinutes(30);
    static final Duration SESSION_LIFETIME = Duration.ofHours(24);

    public AuthProperties {
        if (issuer == null || issuer.isBlank() || audience == null || audience.isBlank()) {
            throw new IllegalArgumentException("JWT issuer and audience are required");
        }
    }
}
