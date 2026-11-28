package com.sona.api.global.auth;

import java.time.Clock;
import java.util.Arrays;
import java.util.Base64;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.core.Ordered;
import org.springframework.core.env.Environment;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.web.servlet.HandlerExceptionResolver;
import org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping;

@Configuration(proxyBeanMethods = false)
@Profile("!mock")
class AuthHttpConfiguration {

    @Bean
    Clock authClock() {
        return Clock.systemUTC();
    }

    @Bean
    JwtTokenService jwtTokenService(AuthKeyMaterial keys, Clock authClock) {
        return new JwtTokenService(new AuthProperties("sona-api", "sona-web"), keys.jwt(), authClock);
    }

    @Bean
    AuthKeyMaterial authKeyMaterial(
            @Value("${sona.auth.csrf-key:}") String key, @Value("${sona.auth.jwt-key:}") String jwtKey) {
        byte[] csrf = decode(key, "SONA_AUTH_CSRF_KEY");
        byte[] jwt = decode(jwtKey, "SONA_AUTH_JWT_KEY");
        if (Arrays.equals(csrf, jwt)) {
            throw new IllegalArgumentException("SONA_AUTH_CSRF_KEY and SONA_AUTH_JWT_KEY must be distinct");
        }
        return new AuthKeyMaterial(jwt, csrf);
    }

    @Bean
    CsrfTokenService csrfTokenService(AuthKeyMaterial keys) {
        return new CsrfTokenService(keys.csrf());
    }

    @Bean
    AuthCookies authCookies(Clock authClock, Environment environment) {
        String[] profiles = environment.getActiveProfiles();
        if (profiles.length == 0) {
            profiles = environment.getDefaultProfiles();
        }
        boolean localOnly = profiles.length == 1 && profiles[0].equals("local");
        return new AuthCookies(authClock, !localOnly);
    }

    @Bean
    RedisAuthSessionStore redisAuthSessionStore(
            StringRedisTemplate redis, @Value("${sona.auth.redis-namespace:sona:auth}") String namespace) {
        return new RedisAuthSessionStore(redis, namespace);
    }

    @Bean
    AuthSessionService authSessionService(JwtTokenService jwt, RedisAuthSessionStore redis) {
        return new AuthSessionService(jwt, redis);
    }

    @Bean
    FilterRegistrationBean<AuthRequestFilter> authRequestFilter(
            AuthSessionService sessions,
            CsrfTokenService csrf,
            @Qualifier("requestMappingHandlerMapping") ObjectProvider<RequestMappingHandlerMapping> mappings,
            @Qualifier("handlerExceptionResolver") ObjectProvider<HandlerExceptionResolver> errors) {
        var registration = new FilterRegistrationBean<>(new AuthRequestFilter(sessions, csrf, mappings, errors));
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE + 20);
        return registration;
    }

    private static byte[] decode(String encoded, String name) {
        try {
            byte[] key = Base64.getDecoder().decode(encoded);
            if (key.length >= 32) {
                return key;
            }
        } catch (IllegalArgumentException ignored) {
            // Do not include the configured value in startup errors.
        }
        throw new IllegalArgumentException(name + " must contain at least 32 Base64-encoded bytes");
    }

    private record AuthKeyMaterial(byte[] jwt, byte[] csrf) {}
}
