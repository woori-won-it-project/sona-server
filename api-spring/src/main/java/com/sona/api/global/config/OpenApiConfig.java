package com.sona.api.global.config;

import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Swagger 문서 설정. 서버 실행 후 /swagger-ui/index.html 에서 본다.
 * 오른쪽 위 Authorize 버튼에 로그인으로 받은 토큰을 넣으면 인증이 필요한 API도 시험할 수 있다.
 */
@Configuration
public class OpenApiConfig {

    private static final String BEARER = "bearerAuth";

    @Bean
    public OpenAPI sonaOpenApi() {
        return new OpenAPI()
                .info(new Info().title("Sona API").version("v1").description("보험 상품설명서 오해 검증 서비스 API"))
                .components(new Components()
                        .addSecuritySchemes(
                                BEARER,
                                new SecurityScheme()
                                        .type(SecurityScheme.Type.HTTP)
                                        .scheme("bearer")))
                .addSecurityItem(new SecurityRequirement().addList(BEARER));
    }
}
