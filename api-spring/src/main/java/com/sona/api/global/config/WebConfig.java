package com.sona.api.global.config;

import com.sona.api.global.auth.LoginMemberArgumentResolver;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final LoginMemberArgumentResolver loginMemberArgumentResolver;
    private final String[] allowedOrigins;

    /** allowedOrigins: 프론트 개발 서버 주소. 쉼표로 여러 개 */
    public WebConfig(
            LoginMemberArgumentResolver loginMemberArgumentResolver,
            @Value("${sona.cors.allowed-origins:http://localhost:5173,http://localhost:3000}")
                    String[] allowedOrigins) {
        this.loginMemberArgumentResolver = loginMemberArgumentResolver;
        this.allowedOrigins = allowedOrigins;
    }

    @Override
    public void addArgumentResolvers(List<HandlerMethodArgumentResolver> resolvers) {
        resolvers.add(loginMemberArgumentResolver);
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**")
                .allowedOrigins(allowedOrigins)
                .allowedMethods("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
                .allowedHeaders("*");
    }
}
