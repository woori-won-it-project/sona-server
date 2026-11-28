package com.sona.api.global.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;
import static org.assertj.core.api.Assertions.assertThatIllegalStateException;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;

import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;

class RedisAuthSessionStoreTest {

    private static final String NAMESPACE = "sona:auth:test22";
    private final JwtTokenService jwt = tokenService();
    private final JwtTokenService.TokenPair pair = jwt.issue(Long.MAX_VALUE);

    @Test
    void createsWithAbsoluteExpiryAndOnlyTheRefreshDigest() {
        var refresh = pair.refresh().claims();
        var redis = redisDouble((script, keys, arguments) -> {
            assertThat(script.contains("'NX', 'PXAT'")).isTrue();
            assertThat(keys).isEqualTo(List.of(sessionKey()));
            String[] parts = arguments[0].split(":");
            assertThat(parts).hasSize(3);
            assertThat(parts[0]).isEqualTo(Long.toString(Long.MAX_VALUE));
            assertThat(parts[1]).isEqualTo(expiry(refresh));
            assertThat(parts[2].equals(refresh.refreshHash())).isTrue();
            assertThat(arguments[0].contains(pair.refresh().value())).isFalse();
            assertThat(arguments[1]).isEqualTo(expiry(refresh));
            return 1L;
        });

        assertThat(new RedisAuthSessionStore(redis, NAMESPACE).create(refresh)).isTrue();
    }

    @Test
    void sendsOldAndNewDigestsInOneCompareAndSetAndRejectsConcurrentReuse() throws Exception {
        var refresh = pair.refresh().claims();
        var first = jwt.prepareRotation(refresh).orElseThrow().refresh().claims();
        var second = jwt.prepareRotation(refresh).orElseThrow().refresh().claims();
        var saved = new AtomicReference<String>();
        var ready = new CountDownLatch(2);
        var redis = redisDouble((script, keys, arguments) -> {
            assertThat(keys).isEqualTo(List.of(sessionKey()));
            if (script.contains("'NX', 'PXAT'")) {
                saved.set(arguments[0]);
                return 1L;
            }
            assertThat(script.contains("'XX', 'KEEPTTL'")).isTrue();
            assertThat(arguments[2]).isEqualTo(expiry(refresh));
            assertThat(arguments[0].equals(arguments[1])).isFalse();
            String observed = saved.get();
            return arguments[0].equals(observed) && saved.compareAndSet(observed, arguments[1]) ? 1L : 0L;
        });
        var store = new RedisAuthSessionStore(redis, NAMESPACE);
        assertThat(store.create(refresh)).isTrue();

        try (var executor = Executors.newFixedThreadPool(2)) {
            var result1 = executor.submit(rotator(ready, () -> store.rotate(refresh, first)));
            var result2 = executor.submit(rotator(ready, () -> store.rotate(refresh, second)));
            assertThat(List.of(result1.get(5, TimeUnit.SECONDS), result2.get(5, TimeUnit.SECONDS)))
                    .containsExactlyInAnyOrder(true, false);
        }
        assertThat(store.rotate(refresh, second)).isFalse();
    }

    @Test
    void passesSessionAndDenyKeysToAccessCheckAndRevocationTogether() {
        var access = pair.access().claims();
        var revoked = new AtomicReference<>(false);
        var redis = redisDouble((script, keys, arguments) -> {
            assertThat(keys)
                    .isEqualTo(List.of(
                            sessionKey(), NAMESPACE + ":access-deny:{" + access.sessionId() + "}:" + access.tokenId()));
            assertThat(arguments).containsExactly(access.memberId() + ":", expiry(access));
            assertThat(script.contains("'EXISTS'")).isTrue();
            if (script.contains("'DEL'")) {
                assertThat(script.contains("'PXAT', ARGV[2]")).isTrue();
                return revoked.getAndSet(true) ? 0L : 1L;
            }
            return revoked.get() ? 0L : 1L;
        });
        var store = new RedisAuthSessionStore(redis, NAMESPACE);

        assertThat(store.isAccessActive(access)).isTrue();
        assertThat(store.revokeByAccess(access)).isTrue();
        assertThat(store.isAccessActive(access)).isFalse();
        assertThat(store.revokeByAccess(access)).isFalse();
    }

    @Test
    void checksTheCurrentRefreshOnRevocationAndDistinguishesMissingDecision() {
        var refresh = pair.refresh().claims();
        var redis = redisDouble((script, keys, arguments) -> {
            assertThat(keys).isEqualTo(List.of(sessionKey()));
            assertThat(script.contains("~= ARGV[1]")).isTrue();
            assertThat(script.contains("'DEL'")).isTrue();
            assertThat(arguments[0].endsWith(":" + refresh.refreshHash())).isTrue();
            assertThat(arguments[1]).isEqualTo(expiry(refresh));
            return 0L;
        });

        assertThat(new RedisAuthSessionStore(redis, NAMESPACE).revokeByRefresh(refresh))
                .isFalse();
        var noDecision = redisDouble((script, keys, arguments) -> null);
        assertThatIllegalStateException()
                .isThrownBy(() -> new RedisAuthSessionStore(noDecision, NAMESPACE).revokeByRefresh(refresh));
    }

    @Test
    void rejectsWrongTokenTypeSessionAndNamespaceBeforeCallingRedis() {
        var redis = mock(StringRedisTemplate.class);
        var store = new RedisAuthSessionStore(redis, NAMESPACE);
        var refresh = pair.refresh().claims();
        var other = jwt.issue(refresh.memberId()).refresh().claims();

        assertThatIllegalArgumentException()
                .isThrownBy(() -> store.create(pair.access().claims()));
        assertThatIllegalArgumentException().isThrownBy(() -> store.isAccessActive(refresh));
        assertThatIllegalArgumentException().isThrownBy(() -> store.rotate(refresh, other));
        assertThatIllegalArgumentException().isThrownBy(() -> store.rotate(refresh, refresh));
        assertThatIllegalArgumentException().isThrownBy(() -> new RedisAuthSessionStore(redis, "invalid{namespace}"));
        verifyNoInteractions(redis);
    }

    private String sessionKey() {
        return NAMESPACE + ":session:{" + pair.refresh().claims().sessionId() + "}";
    }

    private static String expiry(JwtTokenService.VerifiedToken token) {
        return Long.toString(token.expiresAt().toEpochMilli());
    }

    private static Callable<Boolean> rotator(CountDownLatch ready, Callable<Boolean> rotate) {
        return () -> {
            ready.countDown();
            if (!ready.await(5, TimeUnit.SECONDS)) {
                throw new IllegalStateException("Both rotation requests must start");
            }
            return rotate.call();
        };
    }

    private static StringRedisTemplate redisDouble(ScriptCall call) {
        return mock(StringRedisTemplate.class, invocation -> {
            var raw = invocation.getRawArguments();
            var script = (RedisScript<?>) raw[0];
            return call.execute(script.getScriptAsString(), (List<?>) raw[1], (String[]) raw[2]);
        });
    }

    private static JwtTokenService tokenService() {
        byte[] key = new byte[32];
        new SecureRandom().nextBytes(key);
        var clock = Clock.fixed(Instant.parse("2026-11-28T05:00:00Z"), ZoneOffset.UTC);
        return new JwtTokenService(new AuthProperties("sona-test", "sona-test-client"), key, clock);
    }

    private interface ScriptCall {
        Long execute(String script, List<?> keys, String[] arguments);
    }
}
