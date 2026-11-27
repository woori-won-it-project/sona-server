package com.sona.api.global.auth;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 컨트롤러 파라미터에 붙이면 로그인한 회원 ID(Long)가 들어온다. 토큰이 없거나 틀리면 401.
 * 예: public ApiResponse list(@LoginMember Long memberId)
 */
@Target(ElementType.PARAMETER)
@Retention(RetentionPolicy.RUNTIME)
public @interface LoginMember {}
