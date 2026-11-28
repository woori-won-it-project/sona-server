package com.sona.api.global.auth;

import com.sona.api.global.auth.JwtTokenService.IssuedToken;
import com.sona.api.global.auth.JwtTokenService.TokenPair;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.time.Clock;
import java.time.Duration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;

public final class AuthCookies {

    public static final String ACCESS = "accessToken";
    public static final String REFRESH = "refreshToken";
    public static final String CSRF = "XSRF-TOKEN";

    private static final String ACCESS_PATH = "/api/v1";
    private static final String REFRESH_PATH = "/api/v1/auth";

    private final Clock clock;
    private final boolean secure;

    public AuthCookies(Clock clock, boolean secure) {
        this.clock = clock;
        this.secure = secure;
    }

    public void writeTokens(HttpServletResponse response, TokenPair pair) {
        writeToken(response, ACCESS, ACCESS_PATH, pair.access());
        writeToken(response, REFRESH, REFRESH_PATH, pair.refresh());
    }

    private void writeToken(HttpServletResponse response, String name, String path, IssuedToken token) {
        long seconds =
                Duration.between(clock.instant(), token.claims().expiresAt()).toSeconds();
        write(response, name, token.value(), path, true, Math.max(0, seconds));
    }

    public void writeCsrf(HttpServletResponse response, String token) {
        write(response, CSRF, token, "/", false, -1);
    }

    public void clear(HttpServletResponse response) {
        write(response, ACCESS, "", ACCESS_PATH, true, 0);
        write(response, REFRESH, "", REFRESH_PATH, true, 0);
        write(response, CSRF, "", "/", false, 0);
    }

    private void write(
            HttpServletResponse response, String name, String value, String path, boolean httpOnly, long maxAge) {
        ResponseCookie cookie = ResponseCookie.from(name, value)
                .path(path)
                .secure(secure)
                .httpOnly(httpOnly)
                .sameSite("Strict")
                .maxAge(maxAge)
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    static String read(HttpServletRequest request, String name) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) {
            return null;
        }
        Cookie match = null;
        for (Cookie cookie : cookies) {
            if (name.equals(cookie.getName())) {
                if (match != null) {
                    return null;
                }
                match = cookie;
            }
        }
        return match == null ? null : match.getValue();
    }
}
