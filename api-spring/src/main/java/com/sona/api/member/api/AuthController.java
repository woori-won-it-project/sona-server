package com.sona.api.member.api;

import com.sona.api.global.auth.LoginMember;
import com.sona.api.global.response.ApiResponse;
import com.sona.api.global.response.MessageResponse;
import com.sona.api.member.application.AuthService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "1. 회원", description = "로그인 · 로그아웃")
@RestController
@RequestMapping("/api/v1/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    @Operation(summary = "로그인", description = "사번과 비밀번호로 로그인하고 토큰을 받는다.")
    @PostMapping("/login")
    public ApiResponse<LoginResponse> login(@Valid @RequestBody LoginRequest request) {
        return ApiResponse.of(authService.login(request.employeeNumber(), request.password()));
    }

    /** TODO: JWT 도입 시 토큰을 만료 시각까지 Redis 에 막힌 토큰으로 저장 (api.md 2번) */
    @Operation(summary = "로그아웃")
    @PostMapping("/logout")
    public MessageResponse logout(@LoginMember Long memberId) {
        return MessageResponse.of("로그아웃되었습니다.");
    }
}
