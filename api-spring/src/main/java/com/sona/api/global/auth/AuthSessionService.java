package com.sona.api.global.auth;

import com.sona.api.global.auth.JwtTokenService.TokenPair;
import com.sona.api.global.auth.JwtTokenService.VerifiedToken;
import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import jakarta.servlet.http.HttpServletRequest;
import java.util.function.BooleanSupplier;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;

@Slf4j
@RequiredArgsConstructor
public final class AuthSessionService {

    private final JwtTokenService tokens;
    private final RedisAuthSessionStore sessions;

    public TokenPair login(long memberId) {
        TokenPair pair = tokens.issue(memberId);
        if (!execute(() -> sessions.create(pair.refresh().claims()))) {
            throw new BusinessException(ErrorCode.INTERNAL_ERROR);
        }
        return pair;
    }

    public long requireMember(HttpServletRequest request) {
        VerifiedToken access = tokens.verifyAccess(AuthCookies.read(request, AuthCookies.ACCESS))
                .orElseThrow(AuthSessionService::unauthorized);
        if (!execute(() -> sessions.isAccessActive(access))) {
            throw unauthorized();
        }
        return access.memberId();
    }

    public TokenPair refresh(HttpServletRequest request) {
        VerifiedToken current = tokens.verifyRefresh(AuthCookies.read(request, AuthCookies.REFRESH))
                .orElseThrow(AuthSessionService::unauthorized);
        TokenPair replacement = tokens.prepareRotation(current).orElseThrow(AuthSessionService::unauthorized);
        if (!execute(() -> sessions.rotate(current, replacement.refresh().claims()))) {
            throw unauthorized();
        }
        return replacement;
    }

    public void logout(HttpServletRequest request) {
        var access = tokens.verifyAccess(AuthCookies.read(request, AuthCookies.ACCESS));
        if (access.isPresent() && execute(() -> sessions.revokeByAccess(access.orElseThrow()))) {
            return;
        }
        tokens.verifyRefresh(AuthCookies.read(request, AuthCookies.REFRESH))
                .filter(refresh -> access.isEmpty() || sameSession(access.orElseThrow(), refresh))
                .ifPresent(refresh -> execute(() -> sessions.revokeByRefresh(refresh)));
    }

    private static boolean sameSession(VerifiedToken access, VerifiedToken refresh) {
        return access.memberId() == refresh.memberId() && access.sessionId().equals(refresh.sessionId());
    }

    private static boolean execute(BooleanSupplier operation) {
        try {
            return operation.getAsBoolean();
        } catch (DataAccessException | IllegalStateException e) {
            log.warn("인증 세션 저장소 오류 ({})", e.getClass().getSimpleName());
            throw new BusinessException(ErrorCode.INTERNAL_ERROR);
        }
    }

    private static BusinessException unauthorized() {
        return new BusinessException(ErrorCode.UNAUTHORIZED);
    }
}
