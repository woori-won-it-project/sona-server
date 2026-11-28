package com.sona.api.global.auth;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sona.api.global.auth.JwtTokenService.VerifiedToken;
import com.sona.api.global.response.ApiResponse;
import com.sona.api.member.domain.Member;
import com.sona.api.member.domain.MemberRepository;
import com.sona.api.review.domain.Review;
import com.sona.api.review.domain.ReviewRepository;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.Part;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Collection;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestComponent;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.core.Ordered;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.multipart.MultipartFile;

@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
            "sona.cors.allowed-origins=http://localhost:5173",
            "sona.auth.default-member-id=1",
            "sona.llm.provider=mock"
        })
@ActiveProfiles("test")
@Import(AuthHttpTestSupport.TestEndpoints.class)
abstract class AuthHttpTestSupport {

    static final String AUTH = "/api/v1/auth";
    static final String PROTECTED = "/api/v1/personas";
    static final String UPLOAD = "/api/v1/auth-test/multipart";
    static final String EMPLOYEE = "EMP-HTTP-TEST";
    static final Instant NOW = Instant.parse("2026-11-28T05:00:00Z");

    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper json;

    @Autowired
    AtomicInteger multipartParses;

    @MockitoBean
    RedisAuthSessionStore redis;

    @MockitoBean
    MemberRepository members;

    @MockitoBean
    ReviewRepository reviews;

    @MockitoBean(name = "authClock")
    Clock clock;

    private final HttpClient client =
            HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();
    final AtomicReference<Instant> time = new AtomicReference<>();
    private final Map<UUID, UUID> refreshBySession = new ConcurrentHashMap<>();
    final String password = UUID.randomUUID().toString();

    @BeforeEach
    void prepareDoubles() {
        time.set(NOW);
        when(clock.instant()).thenAnswer(invocation -> time.get());
        multipartParses.set(0);
        refreshBySession.clear();
        when(redis.create(any())).thenAnswer(invocation -> {
            VerifiedToken refresh = invocation.getArgument(0);
            return refreshBySession.putIfAbsent(refresh.sessionId(), refresh.tokenId()) == null;
        });
        when(redis.rotate(any(), any())).thenAnswer(invocation -> {
            VerifiedToken old = invocation.getArgument(0);
            VerifiedToken replacement = invocation.getArgument(1);
            return refreshBySession.replace(old.sessionId(), old.tokenId(), replacement.tokenId());
        });
        when(redis.isAccessActive(any())).thenAnswer(invocation -> {
            VerifiedToken access = invocation.getArgument(0);
            return refreshBySession.containsKey(access.sessionId());
        });
        when(redis.revokeByAccess(any())).thenAnswer(invocation -> {
            VerifiedToken access = invocation.getArgument(0);
            return refreshBySession.remove(access.sessionId()) != null;
        });
        when(redis.revokeByRefresh(any())).thenAnswer(invocation -> {
            VerifiedToken refresh = invocation.getArgument(0);
            return refreshBySession.remove(refresh.sessionId(), refresh.tokenId());
        });
        Member member = Member.builder()
                .employeeNumber(EMPLOYEE)
                .name("인증 테스트")
                .passwordHash("{noop}" + password)
                .build();
        ReflectionTestUtils.setField(member, "id", 1L);
        when(members.findByEmployeeNumber(EMPLOYEE)).thenReturn(Optional.of(member));
        Member other = Member.builder().employeeNumber("ANOTHER").build();
        ReflectionTestUtils.setField(other, "id", 2L);
        when(reviews.findById(42L))
                .thenReturn(Optional.of(Review.builder().member(other).build()));
    }

    HttpResponse<String> request(String method, String path, String body, String... headers) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                .timeout(Duration.ofSeconds(10))
                .method(
                        method,
                        body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body));
        if (headers.length > 0) {
            request.headers(headers);
        }
        return client.send(request.build(), HttpResponse.BodyHandlers.ofString());
    }

    JsonNode body(HttpResponse<String> response) throws IOException {
        return json.readTree(response.body());
    }

    String loginBody(String employee, String suppliedPassword) throws IOException {
        return json.writeValueAsString(Map.of("employeeNumber", employee, "password", suppliedPassword));
    }

    HttpResponse<String> csrf() throws Exception {
        return request("GET", AUTH + "/csrf", null);
    }

    HttpResponse<String> login() throws Exception {
        return loginWithCsrf(cookieValue(csrf(), AuthCookies.CSRF));
    }

    HttpResponse<String> loginWithCsrf(String value) throws Exception {
        return request(
                "POST",
                AUTH + "/login",
                loginBody(EMPLOYEE, password),
                "Content-Type",
                "application/json",
                "Cookie",
                cookie(AuthCookies.CSRF, value),
                CsrfTokenService.HEADER,
                value);
    }

    HttpResponse<String> authPost(String operation, String csrf, String cookies) throws Exception {
        return request(
                "POST",
                AUTH + operation,
                null,
                "Cookie",
                cookie(AuthCookies.CSRF, csrf) + cookies,
                CsrfTokenService.HEADER,
                csrf);
    }

    static String cookie(String name, String value) {
        return name + "=" + value;
    }

    static String setCookie(HttpResponse<String> response, String name) {
        return response.headers().allValues("set-cookie").stream()
                .filter(value -> value.startsWith(name + "="))
                .findFirst()
                .orElseThrow(() -> new AssertionError("Missing Set-Cookie for " + name));
    }

    static String cookieValue(HttpResponse<String> response, String name) {
        String header = setCookie(response, name);
        return header.substring(name.length() + 1, header.indexOf(';'));
    }

    @TestConfiguration(proxyBeanMethods = false)
    @Import(MultipartEndpoint.class)
    static class TestEndpoints {

        @Bean
        AtomicInteger multipartParses() {
            return new AtomicInteger();
        }

        @Bean
        FilterRegistrationBean<OncePerRequestFilter> multipartProbe(AtomicInteger multipartParses) {
            var registration = new FilterRegistrationBean<OncePerRequestFilter>(new OncePerRequestFilter() {
                @Override
                protected void doFilterInternal(
                        HttpServletRequest request, HttpServletResponse response, FilterChain chain)
                        throws ServletException, IOException {
                    chain.doFilter(
                            new HttpServletRequestWrapper(request) {
                                @Override
                                public Collection<Part> getParts() throws IOException, ServletException {
                                    multipartParses.incrementAndGet();
                                    return super.getParts();
                                }
                            },
                            response);
                }
            });
            registration.addUrlPatterns(UPLOAD);
            registration.setOrder(Ordered.HIGHEST_PRECEDENCE + 15);
            return registration;
        }
    }

    @RestController
    @TestComponent
    static class MultipartEndpoint {

        @PostMapping(path = UPLOAD, consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
        ApiResponse<Long> upload(@LoginMember Long memberId, @RequestPart("terms") MultipartFile terms) {
            return ApiResponse.of(memberId);
        }
    }
}
