package com.sona.api.member.api;

import com.sona.api.global.auth.AuthCookies;
import com.sona.api.global.auth.AuthSessionService;
import com.sona.api.global.auth.CsrfTokenService;
import com.sona.api.global.response.ApiResponse;
import com.sona.api.global.response.MessageResponse;
import com.sona.api.member.application.AuthService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "1. 회원", description = "쿠키 로그인 · 토큰 재발급 · 로그아웃")
@Profile("!mock")
@RestController
@RequestMapping("/api/v1/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;
    private final AuthSessionService sessions;
    private final AuthCookies cookies;
    private final CsrfTokenService csrf;

    @Operation(summary = "CSRF 토큰 발급")
    @GetMapping("/csrf")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void csrf(HttpServletResponse response) {
        cookies.writeCsrf(response, csrf.issue());
    }

    @Operation(summary = "로그인", description = "사번과 비밀번호를 확인하고 브라우저에 인증 쿠키를 발급합니다.")
    @PostMapping("/login")
    public ApiResponse<LoginResponse> login(@Valid @RequestBody LoginRequest request, HttpServletResponse response) {
        var member = authService.authenticate(request.employeeNumber(), request.password());
        var pair = sessions.login(member.id());
        String csrfToken = csrf.issue();
        cookies.writeTokens(response, pair);
        cookies.writeCsrf(response, csrfToken);
        return ApiResponse.of(new LoginResponse(member));
    }

    @Operation(summary = "토큰 재발급", description = "Refresh 쿠키로 두 인증 쿠키를 갱신합니다.")
    @PostMapping("/refresh")
    public MessageResponse refresh(HttpServletRequest request, HttpServletResponse response) {
        cookies.writeTokens(response, sessions.refresh(request));
        return MessageResponse.of("토큰이 재발급되었습니다.");
    }

    @Operation(summary = "로그아웃", description = "현재 인증 세션을 종료하고 인증·CSRF 쿠키를 삭제합니다.")
    @PostMapping("/logout")
    public MessageResponse logout(HttpServletRequest request, HttpServletResponse response) {
        sessions.logout(request);
        cookies.clear(response);
        return MessageResponse.of("로그아웃되었습니다.");
    }
}
