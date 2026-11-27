package com.sona.api.global.auth;

import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * Authorization: Bearer {토큰} 헤더를 읽어 @LoginMember 파라미터에 회원 ID를 넣는다.
 *
 * <p>sona.auth.default-member-id 가 설정돼 있으면(mock 프로필) 헤더가 없을 때 그 회원으로 본다.
 * Swagger 에서 토큰 없이 바로 시험하기 위한 장치이며, 실제 환경에서는 설정하지 않는다.
 */
@Component
public class LoginMemberArgumentResolver implements HandlerMethodArgumentResolver {

    private static final String BEARER_PREFIX = "Bearer ";

    private final TokenProvider tokenProvider;
    private final Long defaultMemberId;

    public LoginMemberArgumentResolver(
            TokenProvider tokenProvider, @Value("${sona.auth.default-member-id:#{null}}") Long defaultMemberId) {
        this.tokenProvider = tokenProvider;
        this.defaultMemberId = defaultMemberId;
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
                .parseMemberId(header.substring(BEARER_PREFIX.length()).trim())
                .orElseThrow(() -> new BusinessException(ErrorCode.UNAUTHORIZED));
    }
}
