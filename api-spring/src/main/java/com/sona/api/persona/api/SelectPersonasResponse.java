package com.sona.api.persona.api;

import java.util.List;

/** api.md 19 */
public record SelectPersonasResponse(Long reviewId, List<SelectedPersona> selectedPersonas, int selectedCount) {

    public record SelectedPersona(Long reviewPersonaId, Long personaId, String name) {}
}
