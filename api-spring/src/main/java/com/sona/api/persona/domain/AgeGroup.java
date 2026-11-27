package com.sona.api.persona.domain;

/** personas.age_group: 나이대. 근거는 2024 전국민 금융이해력 조사 (spec 4.7.1) */
public enum AgeGroup {
    TWENTIES("20대"),
    FORTIES("40대"),
    SIXTIES("60대");

    private final String label;

    AgeGroup(String label) {
        this.label = label;
    }

    public String label() {
        return label;
    }
}
