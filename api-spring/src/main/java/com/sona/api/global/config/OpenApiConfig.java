package com.sona.api.global.config;

import com.sona.api.global.auth.AuthCookies;
import com.sona.api.global.auth.CsrfTokenService;
import com.sona.api.global.error.ErrorResponse;
import io.swagger.v3.core.converter.ModelConverters;
import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.Operation;
import io.swagger.v3.oas.models.PathItem.HttpMethod;
import io.swagger.v3.oas.models.headers.Header;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.media.Content;
import io.swagger.v3.oas.models.media.MediaType;
import io.swagger.v3.oas.models.media.Schema;
import io.swagger.v3.oas.models.media.StringSchema;
import io.swagger.v3.oas.models.parameters.Parameter;
import io.swagger.v3.oas.models.responses.ApiResponse;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;
import java.util.List;
import java.util.Set;
import org.springdoc.core.customizers.OpenApiCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpHeaders;

@Configuration
public class OpenApiConfig {

    private static final String BEARER = "bearerAuth";
    private static final String COOKIE = "cookieAuth";
    private static final String REFRESH = "refreshCookie";
    private static final String AUTH = "/api/v1/auth";
    private static final Set<HttpMethod> MUTATIONS =
            Set.of(HttpMethod.POST, HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE);

    @Bean
    OpenAPI sonaOpenApi(Environment environment) {
        var api = new OpenAPI()
                .info(new Info().title("Sona API").version("v1").description("보험 상품설명서 오해 검증 서비스 API"))
                .components(new Components());
        if (environment.matchesProfiles("mock")) {
            api.getComponents()
                    .addSecuritySchemes(
                            BEARER,
                            new SecurityScheme().type(SecurityScheme.Type.HTTP).scheme("bearer"));
            return api.addSecurityItem(new SecurityRequirement().addList(BEARER));
        }
        api.getComponents().addSecuritySchemes(COOKIE, cookie(AuthCookies.ACCESS));
        api.getComponents().addSecuritySchemes(REFRESH, cookie(AuthCookies.REFRESH));
        return api.addSecurityItem(new SecurityRequirement().addList(COOKIE));
    }

    @Bean
    OpenApiCustomizer authenticationOperations(Environment environment) {
        boolean mock = environment.matchesProfiles("mock");
        return api -> {
            if (!mock) {
                ModelConverters.getInstance().read(ErrorResponse.class).forEach(api.getComponents()::addSchemas);
            }
            api.getPaths()
                    .forEach((path, item) -> item.readOperationsMap().forEach((method, operation) -> {
                        if ("/api/health".equals(path) || (AUTH + "/login").equals(path)) {
                            operation.setSecurity(List.of());
                        }
                        if (mock || !path.startsWith("/api/v1/")) {
                            return;
                        }
                        if (MUTATIONS.contains(method)) {
                            operation.addParametersItem(new Parameter()
                                    .in("header")
                                    .name(CsrfTokenService.HEADER)
                                    .required(true)
                                    .schema(new StringSchema())
                                    .description("현재 XSRF-TOKEN 쿠키의 값"));
                            error(operation, "403", "INVALID_CSRF_TOKEN");
                        }
                        switch (path) {
                            case AUTH + "/csrf" -> {
                                operation.setSecurity(List.of());
                                operation.getResponses().remove("200");
                                cookies(operation, "204", "XSRF-TOKEN 발급");
                            }
                            case AUTH + "/login" -> {
                                cookies(operation, "200", "Access, Refresh 및 새 XSRF-TOKEN 발급");
                                error(operation, "400", "INVALID_INPUT");
                                error(operation, "401", "LOGIN_FAILED");
                            }
                            case AUTH + "/refresh" -> {
                                operation.setSecurity(List.of(new SecurityRequirement().addList(REFRESH)));
                                cookies(operation, "200", "새 Access 및 Refresh 발급");
                                error(operation, "401", "UNAUTHORIZED");
                            }
                            case AUTH + "/logout" -> {
                                operation.setSecurity(List.of());
                                cookies(operation, "200", "Access, Refresh 및 XSRF-TOKEN 삭제");
                            }
                            default -> error(operation, "401", "UNAUTHORIZED");
                        }
                        if (path.startsWith(AUTH + "/")) {
                            error(operation, "500", "INTERNAL_ERROR");
                        }
                    }));
        };
    }

    private static SecurityScheme cookie(String name) {
        return new SecurityScheme()
                .type(SecurityScheme.Type.APIKEY)
                .in(SecurityScheme.In.COOKIE)
                .name(name)
                .description("동일 출처에서 브라우저가 자동으로 전송하는 HttpOnly 쿠키");
    }

    private static void cookies(Operation operation, String status, String description) {
        operation
                .getResponses()
                .computeIfAbsent(status, ignored -> new ApiResponse().description("성공"))
                .addHeaderObject(
                        HttpHeaders.SET_COOKIE,
                        new Header().description(description).schema(new StringSchema()));
    }

    private static void error(Operation operation, String status, String code) {
        operation
                .getResponses()
                .addApiResponse(
                        status,
                        new ApiResponse()
                                .description(code)
                                .content(new Content()
                                        .addMediaType(
                                                "application/json",
                                                new MediaType()
                                                        .schema(new Schema<>()
                                                                .$ref("#/components/schemas/ErrorResponse")))));
    }
}
