package com.sona.api.global.config;

import com.sona.api.global.auth.CsrfTokenService;
import com.sona.api.global.auth.LoginMemberArgumentResolver;
import java.util.Arrays;
import java.util.List;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpHeaders;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import org.springframework.web.filter.CorsFilter;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final LoginMemberArgumentResolver loginMemberArgumentResolver;

    public WebConfig(LoginMemberArgumentResolver loginMemberArgumentResolver) {
        this.loginMemberArgumentResolver = loginMemberArgumentResolver;
    }

    @Override
    public void addArgumentResolvers(List<HandlerMethodArgumentResolver> resolvers) {
        resolvers.add(loginMemberArgumentResolver);
    }

    @Bean
    FilterRegistrationBean<CorsFilter> apiCorsFilter(Environment environment) {
        boolean mock = environment.matchesProfiles("mock");
        String configuredOrigins = environment.getProperty("sona.cors.allowed-origins", "");
        if (mock && configuredOrigins.isBlank()) {
            configuredOrigins = "http://localhost:5173,http://localhost:3000";
        }
        List<String> origins = Arrays.stream(configuredOrigins.split(","))
                .map(String::trim)
                .filter(origin -> !origin.isEmpty())
                .toList();
        if (!mock && origins.stream().anyMatch(origin -> origin.contains("*"))) {
            throw new IllegalArgumentException("Credentialed CORS requires exact origins");
        }
        var config = new CorsConfiguration();
        config.setAllowedOrigins(origins);
        config.setAllowCredentials(!mock);
        config.setAllowedMethods(List.of("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(mock ? List.of("*") : List.of(HttpHeaders.CONTENT_TYPE, CsrfTokenService.HEADER));
        var source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/api/**", config);
        var registration = new FilterRegistrationBean<>(new CorsFilter(source));
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE + 10);
        return registration;
    }
}
