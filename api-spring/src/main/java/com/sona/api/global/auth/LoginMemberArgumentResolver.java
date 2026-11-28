package com.sona.api.global.auth;

import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.MethodParameter;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/** 실제 요청은 필터가 확인한 회원 ID를 전달한다. mock만 기존 Bearer 경로를 사용한다. */
@Component
public class LoginMemberArgumentResolver implements HandlerMethodArgumentResolver {

    private static final String BEARER_PREFIX = "Bearer ";

    private final ObjectProvider<TokenProvider> tokenProvider;
    private final Long defaultMemberId;
    private final boolean mock;

    public LoginMemberArgumentResolver(
            ObjectProvider<TokenProvider> tokenProvider,
            @Value("${sona.auth.default-member-id:#{null}}") Long defaultMemberId,
            Environment environment) {
        this.tokenProvider = tokenProvider;
        this.defaultMemberId = defaultMemberId;
        this.mock = environment.matchesProfiles("mock");
        if (mock && environment.getActiveProfiles().length != 1) {
            throw new IllegalStateException("The mock profile must be activated on its own");
        }
    }

    @Override
    public boolean supportsParameter(MethodParameter parameter) {
        return parameter.hasParameterAnnotation(LoginMember.class) && Long.class.equals(parameter.getParameterType());
    }

    @Override
    public Long resolveArgument(
            MethodParameter parameter,
            ModelAndViewContainer mavContainer,
            NativeWebRequest webRequest,
            WebDataBinderFactory binderFactory) {
        if (!mock) {
            Object verified = webRequest.getAttribute(AuthRequestFilter.MEMBER_ID, RequestAttributes.SCOPE_REQUEST);
            if (verified instanceof Long memberId) {
                return memberId;
            }
            throw new BusinessException(ErrorCode.UNAUTHORIZED);
        }

        String header = webRequest.getHeader(HttpHeaders.AUTHORIZATION);
        if (header == null || header.isBlank()) {
            if (defaultMemberId != null) {
                return defaultMemberId;
            }
            throw new BusinessException(ErrorCode.UNAUTHORIZED);
        }
        if (!header.startsWith(BEARER_PREFIX)) {
            throw new BusinessException(ErrorCode.UNAUTHORIZED);
        }
        return tokenProvider
                .getObject()
                .parseMemberId(header.substring(BEARER_PREFIX.length()).trim())
                .orElseThrow(() -> new BusinessException(ErrorCode.UNAUTHORIZED));
    }
}
