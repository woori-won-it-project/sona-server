package com.sona.api.member.api;

public record LoginResponse(String accessToken, String tokenType, long expiresIn, MemberInfo member) {

    public record MemberInfo(Long id, String employeeNumber, String name) {}
}
