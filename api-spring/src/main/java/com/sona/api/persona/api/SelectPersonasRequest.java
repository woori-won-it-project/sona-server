package com.sona.api.persona.api;

import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import java.util.List;

/** api.md 19 */
public record SelectPersonasRequest(
        @NotEmpty(message = "페르소나를 1명 이상 골라 주세요.") List<@NotNull Long> personaIds) {}
