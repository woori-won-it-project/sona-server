package com.sona.api.persona.application;

import com.sona.api.persona.domain.Persona;

/** AI 에게 주는 페르소나 소개 글. 나이대·이해 수준·성향·성격 설명(prompt). */
public final class PersonaCard {

    private PersonaCard() {}

    public static String of(Persona p) {
        return "[당신은 이런 사람입니다]\n"
                + p.getAgeGroup().label() + ". " + p.getPrompt() + "\n"
                + "보험 이해 수준: " + literacyText(p) + "\n"
                + "성향: " + p.getDisposition().sentence();
    }

    private static String literacyText(Persona p) {
        return switch (p.getFinancialLiteracy()) {
            case HIGH -> "보험 용어와 조건을 대체로 정확히 이해하는 편";
            case MEDIUM -> "보험 용어를 대략적으로만 아는 편";
            case LOW -> "보험 용어를 잘 모르고, 비슷한 일상 말로 짐작하는 편";
        };
    }
}
