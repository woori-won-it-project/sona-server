package com.sona.api.member.api;

import com.sona.api.global.auth.LoginMember;
import com.sona.api.global.auth.TokenProvider;
import com.sona.api.global.response.ApiResponse;
import com.sona.api.global.response.MessageResponse;
import com.sona.api.member.api.LoginResponse.MemberInfo;
import com.sona.api.member.application.AuthService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Profile;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "1. 회원", description = "mock 로그인 · 로그아웃")
@Profile("mock")
@RestController
@RequestMapping("/api/v1/auth")
@RequiredArgsConstructor
public class MockAuthController {

    private final AuthService authService;
    private final TokenProvider tokens;

    @Operation(summary = "mock 로그인")
    @PostMapping("/login")
    public ApiResponse<MockLoginResponse> login(@Valid @RequestBody LoginRequest request) {
        MemberInfo member = authService.authenticate(request.employeeNumber(), request.password());
        return ApiResponse.of(
                new MockLoginResponse(tokens.issue(member.id()), "Bearer", tokens.expiresInSeconds(), member));
    }

    @Operation(summary = "mock 로그아웃")
    @PostMapping("/logout")
    public MessageResponse logout(@LoginMember Long memberId) {
        return MessageResponse.of("로그아웃되었습니다.");
    }

    public record MockLoginResponse(String accessToken, String tokenType, long expiresIn, MemberInfo member) {}
}
