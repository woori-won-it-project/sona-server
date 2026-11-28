package com.sona.api.global.auth;

import static org.assertj.core.api.Assertions.assertThat;

import java.net.http.HttpResponse;
import java.time.Clock;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletResponse;

class AuthBoundaryHttpTest extends AuthHttpTestSupport {

    @Test
    void preservesPublicNotFoundAndOwnershipBoundaries() throws Exception {
        assertThat(request("GET", "/api/health", null).statusCode()).isEqualTo(200);
        assertThat(request("GET", "/swagger-ui/index.html", null).statusCode()).isEqualTo(200);
        assertError(request("GET", "/api/v1/not-mapped", null), 404, "NOT_FOUND");
        assertError(request("GET", PROTECTED, null), 401, "UNAUTHORIZED");
        assertError(request("GET", PROTECTED, null, "Authorization", "Bearer mock-1"), 401, "UNAUTHORIZED");

        var login = login();
        String access = cookie(AuthCookies.ACCESS, cookieValue(login, AuthCookies.ACCESS));
        assertError(request("GET", "/api/v1/reviews/42/experiments", null, "Cookie", access), 404, "NOT_FOUND");
        assertError(request("GET", PROTECTED, null, "Cookie", access + "; " + access), 401, "UNAUTHORIZED");
    }

    @Test
    void corsPreflightRunsWithoutCookiesAndActualErrorsKeepCorsHeaders() throws Exception {
        String origin = "http://localhost:5173";
        var preflight = request(
                "OPTIONS",
                UPLOAD,
                null,
                "Origin",
                origin,
                "Access-Control-Request-Method",
                "POST",
                "Access-Control-Request-Headers",
                "content-type,x-xsrf-token");
        assertThat(preflight.statusCode()).isEqualTo(200);
        assertThat(preflight.headers().firstValue("access-control-allow-origin"))
                .contains(origin);
        assertThat(preflight.headers().firstValue("access-control-allow-credentials"))
                .contains("true");
        assertThat(preflight
                        .headers()
                        .firstValue("access-control-allow-headers")
                        .orElse(""))
                .containsIgnoringCase("X-XSRF-TOKEN");

        var actual = request("GET", PROTECTED, null, "Origin", origin);
        assertError(actual, 401, "UNAUTHORIZED");
        assertThat(actual.headers().firstValue("access-control-allow-origin")).contains(origin);
        var blocked = request(
                "OPTIONS", UPLOAD, null, "Origin", "https://other.example", "Access-Control-Request-Method", "POST");
        assertThat(blocked.statusCode()).isEqualTo(403);
        assertThat(blocked.headers().firstValue("access-control-allow-origin")).isEmpty();
    }

    @Test
    void checksAuthAndCsrfBeforeActualMultipartParsing() throws Exception {
        String data = """
                --probe\r
                Content-Disposition: form-data; name="terms"; filename="sample.pdf"\r
                Content-Type: application/pdf\r
                \r
                test data\r
                --probe--\r
                """;
        String multipart = "multipart/form-data; boundary=probe";

        assertError(request("POST", UPLOAD, data, "Content-Type", multipart), 401, "UNAUTHORIZED");
        assertThat(multipartParses.get()).isZero();
        var login = login();
        String access = cookie(AuthCookies.ACCESS, cookieValue(login, AuthCookies.ACCESS));
        assertError(
                request("POST", UPLOAD, data, "Content-Type", multipart, "Cookie", access), 403, "INVALID_CSRF_TOKEN");
        assertThat(multipartParses.get()).isZero();

        String csrf = cookieValue(login, AuthCookies.CSRF);
        var accepted = request(
                "POST",
                UPLOAD,
                data,
                "Content-Type",
                multipart,
                "Cookie",
                access + "; " + cookie(AuthCookies.CSRF, csrf),
                CsrfTokenService.HEADER,
                csrf);
        assertThat(accepted.statusCode()).isEqualTo(200);
        assertThat(body(accepted).path("data").asLong()).isEqualTo(1L);
        assertThat(multipartParses.get()).isPositive();
    }

    @Test
    void documentsActualCookieAndCsrfContracts() throws Exception {
        var documents = request("GET", "/v3/api-docs", null);
        assertThat(documents.statusCode()).isEqualTo(200);
        var openApi = body(documents);
        var schemes = openApi.path("components").path("securitySchemes");
        assertThat(schemes.path("cookieAuth").path("in").asText()).isEqualTo("cookie");
        assertThat(schemes.path("cookieAuth").path("name").asText()).isEqualTo("accessToken");
        assertThat(schemes.has("bearerAuth")).isFalse();
        var paths = openApi.path("paths");
        var csrf = paths.path(AUTH + "/csrf").path("get");
        assertThat(csrf.path("security").isEmpty()).isTrue();
        assertThat(csrf.path("responses").path("204").path("headers").has("Set-Cookie"))
                .isTrue();
        var login = paths.path(AUTH + "/login").path("post");
        assertThat(login.path("security").isEmpty()).isTrue();
        assertThat(login.path("responses").path("401").path("description").asText())
                .isEqualTo("LOGIN_FAILED");
        var refresh = paths.path(AUTH + "/refresh").path("post");
        assertThat(refresh.path("security").path(0).has("refreshCookie")).isTrue();
        var logout = paths.path(AUTH + "/logout").path("post");
        assertThat(logout.path("responses").path("200").path("headers").has("Set-Cookie"))
                .isTrue();
        var upload = paths.path(UPLOAD).path("post");
        assertThat(upload.path("parameters").path(0).path("name").asText()).isEqualTo(CsrfTokenService.HEADER);
        assertThat(upload.path("responses").path("403").path("description").asText())
                .isEqualTo("INVALID_CSRF_TOKEN");
    }

    @Test
    void localCookieWriterCanIssueNonSecureHostOnlyCookie() {
        var response = new MockHttpServletResponse();
        new AuthCookies(Clock.systemUTC(), false).writeCsrf(response, "test-value");
        String cookie = response.getHeader("Set-Cookie");
        assertThat(cookie).contains("Path=/", "SameSite=Strict").doesNotContain("Secure", "Domain");
    }

    private void assertError(HttpResponse<String> response, int status, String code) throws Exception {
        assertThat(response.statusCode()).isEqualTo(status);
        assertThat(body(response).path("code").asText()).isEqualTo(code);
    }
}
