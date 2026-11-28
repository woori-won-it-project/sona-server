package com.sona.api.global.auth;

import com.sona.api.global.error.BusinessException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Set;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.HttpHeaders;
import org.springframework.http.server.PathContainer;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.HandlerExceptionResolver;
import org.springframework.web.servlet.mvc.method.RequestMappingInfo;
import org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping;
import org.springframework.web.util.ServletRequestPathUtils;
import org.springframework.web.util.pattern.PathPattern;
import org.springframework.web.util.pattern.PathPatternParser;

final class AuthRequestFilter extends OncePerRequestFilter {

    static final String MEMBER_ID = AuthRequestFilter.class.getName() + ".memberId";

    private static final PathPattern API = path("/api/v1/**");
    private static final PathPattern CSRF = path("/api/v1/auth/csrf");
    private static final Set<PathPattern> AUTH_MUTATIONS =
            Set.of(path("/api/v1/auth/login"), path("/api/v1/auth/refresh"), path("/api/v1/auth/logout"));
    private static final Set<String> MUTATIONS = Set.of("POST", "PUT", "PATCH", "DELETE");

    private final AuthSessionService sessions;
    private final CsrfTokenService csrf;
    private final ObjectProvider<RequestMappingHandlerMapping> mappings;
    private final ObjectProvider<HandlerExceptionResolver> errors;

    AuthRequestFilter(
            AuthSessionService sessions,
            CsrfTokenService csrf,
            ObjectProvider<RequestMappingHandlerMapping> mappings,
            ObjectProvider<HandlerExceptionResolver> errors) {
        this.sessions = sessions;
        this.csrf = csrf;
        this.mappings = mappings;
        this.errors = errors;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        try {
            authenticate(request, response);
        } catch (BusinessException e) {
            if (errors.getObject().resolveException(request, response, null, e) == null) {
                throw e;
            }
            return;
        }
        chain.doFilter(request, response);
    }

    private void authenticate(HttpServletRequest request, HttpServletResponse response) {
        String method = request.getMethod();
        if ("OPTIONS".equals(method)) {
            return;
        }
        var path = ServletRequestPathUtils.parseAndCache(request).pathWithinApplication();
        if (!API.matches(path)) {
            return;
        }
        if (("GET".equals(method) || "HEAD".equals(method)) && CSRF.matches(path)) {
            response.setHeader(HttpHeaders.CACHE_CONTROL, "no-store");
            return;
        }
        if ("POST".equals(method) && AUTH_MUTATIONS.stream().anyMatch(pattern -> pattern.matches(path))) {
            response.setHeader(HttpHeaders.CACHE_CONTROL, "no-store");
            csrf.verify(request);
            return;
        }
        // Match registration metadata only. MVC's full matching may inspect multipart form parameters.
        boolean mapped = mappings.getObject().getHandlerMethods().keySet().stream()
                .anyMatch(info -> matches(info, path, method));
        if (mapped) {
            long memberId = sessions.requireMember(request);
            if (MUTATIONS.contains(method)) {
                csrf.verify(request);
            }
            request.setAttribute(MEMBER_ID, memberId);
        }
    }

    private static boolean matches(RequestMappingInfo info, PathContainer path, String method) {
        var patterns = info.getPathPatternsCondition();
        var methods = info.getMethodsCondition().getMethods();
        return patterns != null
                && (methods.isEmpty()
                        || methods.stream()
                                .anyMatch(registered -> registered.name().equals(method)
                                        || registered == RequestMethod.GET && "HEAD".equals(method)))
                && patterns.getPatterns().stream().anyMatch(pattern -> pattern.matches(path));
    }

    private static PathPattern path(String pattern) {
        return PathPatternParser.defaultInstance.parse(pattern);
    }
}
