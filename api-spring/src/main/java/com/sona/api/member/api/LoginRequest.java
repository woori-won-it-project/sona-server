package com.sona.api.member.api;

import jakarta.validation.constraints.NotBlank;

public record LoginRequest(
        @NotBlank(message = "사번을 입력해 주세요.") String employeeNumber,
        @NotBlank(message = "비밀번호를 입력해 주세요.") String password) {}
