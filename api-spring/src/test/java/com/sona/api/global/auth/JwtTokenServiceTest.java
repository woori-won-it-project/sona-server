package com.sona.api.global.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;

import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import org.junit.jupiter.api.Test;

class JwtTokenServiceTest {

    private static final Instant NOW = Instant.parse("2026-11-28T05:00:00Z");
    private static final AuthProperties PROPERTIES = new AuthProperties("sona-test", "sona-test-client");

    private final byte[] key = randomKey();
    private final JwtTokenService tokens = serviceAt(NOW);

    @Test
    void verifiesBothTypesForTheSameMemberAndSession() {
        var pair = tokens.issue(Long.MAX_VALUE);
        var access = tokens.verifyAccess(pair.access().value()).orElseThrow();
        var refresh = tokens.verifyRefresh(pair.refresh().value()).orElseThrow();

        assertThat(access.memberId()).isEqualTo(Long.MAX_VALUE);
        assertThat(refresh.memberId()).isEqualTo(access.memberId());
        assertThat(refresh.sessionId()).isEqualTo(access.sessionId());
        assertThat(refresh.tokenId()).isNotEqualTo(access.tokenId());
        assertThat(access.expiresAt()).isEqualTo(NOW.plusSeconds(1800));
        assertThat(refresh.expiresAt()).isEqualTo(NOW.plusSeconds(86400));
        assertThat(tokens.verifyRefresh(pair.access().value())).isEmpty();
        assertThat(tokens.verifyAccess(pair.refresh().value())).isEmpty();
        assertThat(pair.toString().contains(pair.refresh().value())).isFalse();
        assertThat(pair.toString().contains(pair.access().value())).isFalse();
    }

    @Test
    void rejectsInvalidSignatureIssuerAudienceAndInput() {
        String value = tokens.issue(1).access().value();
        int signature = value.lastIndexOf('.') + 1;
        char replacement = value.charAt(signature) == 'A' ? 'B' : 'A';
        String tampered = value.substring(0, signature) + replacement + value.substring(signature + 1);

        assertThat(tokens.verifyAccess(tampered)).isEmpty();
        assertThat(new JwtTokenService(PROPERTIES, randomKey(), fixedClock(NOW)).verifyAccess(value))
                .isEmpty();
        assertThat(new JwtTokenService(new AuthProperties("other", PROPERTIES.audience()), key, fixedClock(NOW))
                        .verifyAccess(value))
                .isEmpty();
        assertThat(new JwtTokenService(new AuthProperties(PROPERTIES.issuer(), "other"), key, fixedClock(NOW))
                        .verifyAccess(value))
                .isEmpty();
        assertThat(tokens.verifyAccess(null)).isEmpty();
        assertThat(tokens.verifyAccess("not-a-jwt")).isEmpty();
        assertThat(tokens.verifyAccess("a".repeat(4097))).isEmpty();
        assertThatIllegalArgumentException().isThrownBy(() -> tokens.issue(0));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new JwtTokenService(PROPERTIES, new byte[31], fixedClock(NOW)));
    }

    @Test
    void expiresAtTheBoundaryAndRejectsFutureIssuance() {
        var pair = tokens.issue(1);
        assertThat(serviceAt(NOW.minusSeconds(1)).verifyAccess(pair.access().value()))
                .isEmpty();
        assertThat(serviceAt(NOW.plusSeconds(1799)).verifyAccess(pair.access().value()))
                .isPresent();
        assertThat(serviceAt(NOW.plusSeconds(1800)).verifyAccess(pair.access().value()))
                .isEmpty();
        assertThat(serviceAt(NOW.plusSeconds(86400))
                        .verifyRefresh(pair.refresh().value()))
                .isEmpty();
        assertThat(serviceAt(NOW.plusSeconds(86400))
                        .prepareRotation(pair.refresh().claims()))
                .isEmpty();
    }

    @Test
    void rotationKeepsAbsoluteExpiryAndCapsAccessToRemainingTime() {
        var pair = tokens.issue(1);
        var later = serviceAt(NOW.plusSeconds(86399));
        var current = later.verifyRefresh(pair.refresh().value()).orElseThrow();
        var next = later.prepareRotation(current).orElseThrow();

        assertThat(next.access().claims().expiresAt()).isEqualTo(current.expiresAt());
        assertThat(next.refresh().claims().expiresAt()).isEqualTo(current.expiresAt());
        assertThat(next.refresh().claims().sessionId()).isEqualTo(current.sessionId());
        assertThat(next.refresh().claims().tokenId()).isNotEqualTo(current.tokenId());
        assertThat(later.verifyAccess(next.access().value())).isPresent();
        assertThat(later.verifyRefresh(next.refresh().value())).isPresent();
    }

    private JwtTokenService serviceAt(Instant now) {
        return new JwtTokenService(PROPERTIES, key, fixedClock(now));
    }

    private static Clock fixedClock(Instant now) {
        return Clock.fixed(now, ZoneOffset.UTC);
    }

    private static byte[] randomKey() {
        byte[] key = new byte[32];
        new SecureRandom().nextBytes(key);
        return key;
    }
}
