package com.sona.api.global.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verifyNoInteractions;

import java.net.http.HttpResponse;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;

class CookieAuthFlowTest extends AuthHttpTestSupport {

    @Test
    void issuesCsrfAndReturnsMemberAndCookiesOnLogin() throws Exception {
        var issuance = csrf();
        assertThat(issuance.statusCode()).isEqualTo(204);
        assertThat(issuance.body()).isEmpty();
        assertThat(issuance.headers().firstValue("cache-control")).contains("no-store");
        String originalCsrf = cookieValue(issuance, AuthCookies.CSRF);
        assertCookie(issuance, AuthCookies.CSRF, "/", false, null);

        var login = loginWithCsrf(originalCsrf);
        assertThat(login.statusCode()).isEqualTo(200);
        var data = body(login).path("data");
        assertThat(data.size()).isEqualTo(1);
        assertThat(data.path("member").path("id").asLong()).isEqualTo(1L);
        assertThat(data.path("member").path("employeeNumber").asText()).isEqualTo(EMPLOYEE);
        assertCookie(login, AuthCookies.ACCESS, "/api/v1", true, 1800);
        assertCookie(login, AuthCookies.REFRESH, "/api/v1/auth", true, 86400);
        assertCookie(login, AuthCookies.CSRF, "/", false, null);
        assertThat(cookieValue(login, AuthCookies.CSRF).equals(originalCsrf)).isFalse();
    }

    @Test
    void rejectsMissingForgedMismatchedAndDuplicatedCsrfBeforeCredentials() throws Exception {
        String csrf = cookieValue(csrf(), AuthCookies.CSRF);
        String other = cookieValue(csrf(), AuthCookies.CSRF);
        String invalid = (csrf.startsWith("A") ? "B" : "A") + csrf.substring(1);
        String login = loginBody(EMPLOYEE, password);
        assertError(
                request("POST", AUTH + "/login", login, "Content-Type", "application/json"), 403, "INVALID_CSRF_TOKEN");
        assertError(loginWithCsrf(invalid), 403, "INVALID_CSRF_TOKEN");
        assertError(
                request(
                        "POST",
                        AUTH + "/login",
                        login,
                        "Content-Type",
                        "application/json",
                        "Cookie",
                        cookie(AuthCookies.CSRF, csrf),
                        CsrfTokenService.HEADER,
                        other),
                403,
                "INVALID_CSRF_TOKEN");
        assertError(
                request(
                        "POST",
                        AUTH + "/login",
                        login,
                        "Content-Type",
                        "application/json",
                        "Cookie",
                        cookie(AuthCookies.CSRF, csrf),
                        CsrfTokenService.HEADER,
                        csrf,
                        CsrfTokenService.HEADER,
                        csrf),
                403,
                "INVALID_CSRF_TOKEN");
        assertError(
                request(
                        "POST",
                        AUTH + "/login",
                        login,
                        "Content-Type",
                        "application/json",
                        "Cookie",
                        cookie(AuthCookies.CSRF, csrf) + "; " + cookie(AuthCookies.CSRF, csrf),
                        CsrfTokenService.HEADER,
                        csrf),
                403,
                "INVALID_CSRF_TOKEN");
        verifyNoInteractions(members, redis);
    }

    @Test
    void keepsLoginValidationAndCredentialErrors() throws Exception {
        String csrf = cookieValue(csrf(), AuthCookies.CSRF);
        for (String employee : List.of(EMPLOYEE, "UNKNOWN")) {
            assertError(
                    request(
                            "POST",
                            AUTH + "/login",
                            loginBody(employee, password + "wrong"),
                            "Content-Type",
                            "application/json",
                            "Cookie",
                            cookie(AuthCookies.CSRF, csrf),
                            CsrfTokenService.HEADER,
                            csrf),
                    401,
                    "LOGIN_FAILED");
        }
        var invalid = request(
                "POST",
                AUTH + "/login",
                "{}",
                "Content-Type",
                "application/json",
                "Cookie",
                cookie(AuthCookies.CSRF, csrf),
                CsrfTokenService.HEADER,
                csrf);
        assertError(invalid, 400, "INVALID_INPUT");
        assertThat(body(invalid).path("details").path("employeeNumber").isTextual())
                .isTrue();
        verifyNoInteractions(redis);
    }

    @Test
    void refreshesWithoutAccessAndOnlyOneRequestCanRotate() throws Exception {
        var login = login();
        String csrf = cookieValue(login, AuthCookies.CSRF);
        String oldRefresh = pairCookie(login, AuthCookies.REFRESH);
        time.set(NOW.plusSeconds(1800));
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var first = executor.submit(() -> authPost("/refresh", csrf, oldRefresh));
            var second = executor.submit(() -> authPost("/refresh", csrf, oldRefresh));
            var a = first.get(10, TimeUnit.SECONDS);
            var b = second.get(10, TimeUnit.SECONDS);
            assertThat(List.of(a.statusCode(), b.statusCode())).containsExactlyInAnyOrder(200, 401);
            var winner = a.statusCode() == 200 ? a : b;
            var loser = a.statusCode() == 401 ? a : b;
            assertThat(body(winner).path("message").asText()).isEqualTo("토큰이 재발급되었습니다.");
            assertCookie(winner, AuthCookies.ACCESS, "/api/v1", true, 1800);
            assertCookie(winner, AuthCookies.REFRESH, "/api/v1/auth", true, 84600);
            assertThat(loser.headers().allValues("set-cookie")).isEmpty();
            assertError(loser, 401, "UNAUTHORIZED");
            assertError(authPost("/refresh", csrf, oldRefresh), 401, "UNAUTHORIZED");
            assertThat(getWithAccess(winner).statusCode()).isEqualTo(200);
            var withExpiredAccess = authPost(
                    "/refresh", csrf, pairCookie(login, AuthCookies.ACCESS) + pairCookie(winner, AuthCookies.REFRESH));
            assertThat(withExpiredAccess.statusCode()).isEqualTo(200);
        }
    }

    @Test
    void logoutWithOldAccessRevokesRotatedSessionAndRemainsIdempotent() throws Exception {
        var login = login();
        String csrf = cookieValue(login, AuthCookies.CSRF);
        var rotated = authPost("/refresh", csrf, pairCookie(login, AuthCookies.REFRESH));
        assertThat(rotated.statusCode()).isEqualTo(200);
        assertThat(getWithAccess(login).statusCode()).isEqualTo(200);

        var logout = authPost("/logout", csrf, pairCookie(login, AuthCookies.ACCESS));
        assertDeleted(logout);
        assertError(getWithAccess(login), 401, "UNAUTHORIZED");
        assertError(getWithAccess(rotated), 401, "UNAUTHORIZED");
        assertError(authPost("/refresh", csrf, pairCookie(rotated, AuthCookies.REFRESH)), 401, "UNAUTHORIZED");
        assertDeleted(authPost("/logout", csrf, ""));
        assertThat(loginWithCsrf(cookieValue(csrf(), AuthCookies.CSRF)).statusCode())
                .isEqualTo(200);
    }

    @Test
    void concurrentAccessLogoutPreventsSessionResurrection() throws Exception {
        var login = login();
        String csrf = cookieValue(login, AuthCookies.CSRF);
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var refresh = executor.submit(() -> authPost("/refresh", csrf, pairCookie(login, AuthCookies.REFRESH)));
            var logout = executor.submit(() -> authPost("/logout", csrf, pairCookie(login, AuthCookies.ACCESS)));
            assertDeleted(logout.get(10, TimeUnit.SECONDS));
            var response = refresh.get(10, TimeUnit.SECONDS);
            assertThat(response.statusCode()).isIn(200, 401);
            assertError(getWithAccess(login), 401, "UNAUTHORIZED");
            if (response.statusCode() == 200) {
                assertError(getWithAccess(response), 401, "UNAUTHORIZED");
                assertError(authPost("/refresh", csrf, pairCookie(response, AuthCookies.REFRESH)), 401, "UNAUTHORIZED");
            } else {
                assertThat(response.headers().allValues("set-cookie")).isEmpty();
            }
        }
    }

    @Test
    void expiredAccessUsesCurrentRefreshButRotatedRefreshCannotRevoke() throws Exception {
        var login = login();
        String csrf = cookieValue(login, AuthCookies.CSRF);
        time.set(NOW.plusSeconds(1800));
        var rotated = authPost("/refresh", csrf, pairCookie(login, AuthCookies.REFRESH));
        assertThat(rotated.statusCode()).isEqualTo(200);
        assertDeleted(authPost(
                "/logout", csrf, pairCookie(login, AuthCookies.ACCESS) + pairCookie(login, AuthCookies.REFRESH)));
        assertThat(getWithAccess(rotated).statusCode()).isEqualTo(200);
        assertDeleted(authPost(
                "/logout", csrf, pairCookie(login, AuthCookies.ACCESS) + pairCookie(rotated, AuthCookies.REFRESH)));
        assertError(getWithAccess(rotated), 401, "UNAUTHORIZED");
    }

    @Test
    void logoutWithDifferentSessionCookiesOnlyRevokesTheAccessSession() throws Exception {
        var first = login();
        var second = login();
        String csrf = cookieValue(first, AuthCookies.CSRF);
        assertDeleted(authPost(
                "/logout", csrf, pairCookie(first, AuthCookies.ACCESS) + pairCookie(second, AuthCookies.REFRESH)));
        assertDeleted(authPost(
                "/logout", csrf, pairCookie(first, AuthCookies.ACCESS) + pairCookie(second, AuthCookies.REFRESH)));
        assertError(getWithAccess(first), 401, "UNAUTHORIZED");
        assertThat(getWithAccess(second).statusCode()).isEqualTo(200);
    }

    @Test
    void redisFailuresRejectProtectionAndDoNotSetCookies() throws Exception {
        var login = login();
        String csrf = cookieValue(login, AuthCookies.CSRF);
        var outage = new DataAccessResourceFailureException("test outage");
        doThrow(outage).when(redis).create(any());
        doThrow(outage).when(redis).isAccessActive(any());
        doThrow(outage).when(redis).rotate(any(), any());
        doThrow(outage).when(redis).revokeByAccess(any());
        for (var response : List.of(
                loginWithCsrf(csrf),
                getWithAccess(login),
                authPost("/refresh", csrf, pairCookie(login, AuthCookies.REFRESH)),
                authPost("/logout", csrf, pairCookie(login, AuthCookies.ACCESS)))) {
            assertError(response, 500, "INTERNAL_ERROR");
            assertThat(response.headers().allValues("set-cookie")).isEmpty();
        }
    }

    void assertError(HttpResponse<String> response, int status, String code) throws Exception {
        assertThat(response.statusCode()).isEqualTo(status);
        assertThat(body(response).path("code").asText()).isEqualTo(code);
        assertThat(body(response).path("message").isTextual()).isTrue();
    }

    private HttpResponse<String> getWithAccess(HttpResponse<String> auth) throws Exception {
        return request(
                "GET", PROTECTED, null, "Cookie", cookie(AuthCookies.ACCESS, cookieValue(auth, AuthCookies.ACCESS)));
    }

    private static String pairCookie(HttpResponse<String> auth, String name) {
        return "; " + cookie(name, cookieValue(auth, name));
    }

    private static void assertCookie(
            HttpResponse<String> response, String name, String path, boolean httpOnly, Integer maxAge) {
        String cookie = setCookie(response, name);
        assertThat(cookie.contains("; Path=" + path + ";")).as(name + " Path").isTrue();
        assertThat(cookie.contains("; HttpOnly")).as(name + " HttpOnly").isEqualTo(httpOnly);
        assertThat(cookie.contains("; Secure")).as(name + " Secure").isTrue();
        assertThat(cookie.contains("; SameSite=Strict")).as(name + " SameSite").isTrue();
        assertThat(cookie.contains("; Domain=")).as(name + " host-only").isFalse();
        if (maxAge == null) {
            assertThat(cookie.contains("; Max-Age="))
                    .as(name + " session cookie")
                    .isFalse();
        } else {
            assertThat(cookie.contains("; Max-Age=" + maxAge + ";"))
                    .as(name + " Max-Age")
                    .isTrue();
        }
    }

    private void assertDeleted(HttpResponse<String> logout) throws Exception {
        assertThat(logout.statusCode()).isEqualTo(200);
        assertThat(body(logout).path("message").asText()).isEqualTo("로그아웃되었습니다.");
        assertCookie(logout, AuthCookies.ACCESS, "/api/v1", true, 0);
        assertCookie(logout, AuthCookies.REFRESH, "/api/v1/auth", true, 0);
        assertCookie(logout, AuthCookies.CSRF, "/", false, 0);
        assertThat(logout.headers().allValues("set-cookie").stream().allMatch(cookie -> cookie.contains("=;")))
                .isTrue();
    }
}
