package com.sona.api.global.auth;

import com.sona.api.global.auth.JwtTokenService.TokenUse;
import com.sona.api.global.auth.JwtTokenService.VerifiedToken;
import java.util.List;
import java.util.Objects;
import java.util.regex.Pattern;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;

/** Stores only the session identity, absolute expiration and current refresh digest. */
public final class RedisAuthSessionStore {

    private static final Pattern NAMESPACE = Pattern.compile("[a-zA-Z0-9:_-]{1,96}");
    private static final String REDIS_TIME = """
            local time = redis.call('TIME')
            local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
            """;

    private static final RedisScript<Long> CREATE = script(REDIS_TIME + """
            if tonumber(ARGV[2]) <= now then return 0 end
            if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'PXAT', ARGV[2]) then return 1 end
            return 0
            """);

    private static final RedisScript<Long> ROTATE = script(REDIS_TIME + """
            if tonumber(ARGV[3]) <= now or redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
            if redis.call('SET', KEYS[1], ARGV[2], 'XX', 'KEEPTTL') then return 1 end
            return 0
            """);

    private static final String MATCH_ACCESS_SESSION = REDIS_TIME + """
            if tonumber(ARGV[2]) <= now then return 0 end
            local session = redis.call('GET', KEYS[1])
            if not session or string.sub(session, 1, #ARGV[1]) ~= ARGV[1] then return 0 end
            """;

    private static final RedisScript<Long> CHECK_ACCESS = script(MATCH_ACCESS_SESSION + """
            if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
            return 1
            """);

    private static final RedisScript<Long> REVOKE_BY_ACCESS = script(MATCH_ACCESS_SESSION + """
            if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
            redis.call('SET', KEYS[2], '1', 'PXAT', ARGV[2])
            return redis.call('DEL', KEYS[1])
            """);

    private static final RedisScript<Long> REVOKE_BY_REFRESH = script(REDIS_TIME + """
            if tonumber(ARGV[2]) <= now or redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
            return redis.call('DEL', KEYS[1])
            """);

    private final StringRedisTemplate redis;
    private final String namespace;

    public RedisAuthSessionStore(StringRedisTemplate redis, String namespace) {
        this.redis = Objects.requireNonNull(redis);
        if (namespace == null || !NAMESPACE.matcher(namespace).matches()) {
            throw new IllegalArgumentException("Invalid Redis authentication namespace");
        }
        this.namespace = namespace;
    }

    public boolean create(VerifiedToken refresh) {
        return execute(CREATE, List.of(sessionKey(refresh)), sessionValue(refresh), expiryMillis(refresh));
    }

    public boolean rotate(VerifiedToken current, VerifiedToken replacement) {
        String currentValue = sessionValue(current);
        String replacementValue = sessionValue(replacement);
        if (current.memberId() != replacement.memberId()
                || !current.sessionId().equals(replacement.sessionId())
                || !current.expiresAt().equals(replacement.expiresAt())
                || current.tokenId().equals(replacement.tokenId())
                || currentValue.equals(replacementValue)) {
            throw new IllegalArgumentException("Invalid refresh replacement");
        }
        return execute(ROTATE, List.of(sessionKey(current)), currentValue, replacementValue, expiryMillis(current));
    }

    public boolean isAccessActive(VerifiedToken access) {
        return executeAccess(CHECK_ACCESS, access);
    }

    public boolean revokeByAccess(VerifiedToken access) {
        return executeAccess(REVOKE_BY_ACCESS, access);
    }

    public boolean revokeByRefresh(VerifiedToken refresh) {
        return execute(REVOKE_BY_REFRESH, List.of(sessionKey(refresh)), sessionValue(refresh), expiryMillis(refresh));
    }

    private boolean executeAccess(RedisScript<Long> script, VerifiedToken access) {
        access.requireUse(TokenUse.ACCESS);
        String denyKey = namespace + ":access-deny:" + hashTag(access) + ":" + access.tokenId();
        return execute(script, List.of(sessionKey(access), denyKey), access.memberId() + ":", expiryMillis(access));
    }

    private String sessionKey(VerifiedToken token) {
        return namespace + ":session:" + hashTag(token);
    }

    private static String hashTag(VerifiedToken token) {
        return "{" + token.sessionId() + "}";
    }

    private static String sessionValue(VerifiedToken refresh) {
        return refresh.memberId() + ":" + expiryMillis(refresh) + ":" + refresh.refreshHash();
    }

    private static String expiryMillis(VerifiedToken token) {
        return Long.toString(token.expiresAt().toEpochMilli());
    }

    private boolean execute(RedisScript<Long> script, List<String> keys, String... arguments) {
        Long result = redis.execute(script, keys, (Object[]) arguments);
        if (Long.valueOf(1).equals(result)) {
            return true;
        }
        if (Long.valueOf(0).equals(result)) {
            return false;
        }
        throw new IllegalStateException("Redis authentication operation returned no decision");
    }

    private static RedisScript<Long> script(String source) {
        return new DefaultRedisScript<>(source, Long.class);
    }
}
