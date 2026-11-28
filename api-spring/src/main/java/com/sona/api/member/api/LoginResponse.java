package com.sona.api.member.api;

public record LoginResponse(MemberInfo member) {

    public record MemberInfo(Long id, String employeeNumber, String name) {}
}
