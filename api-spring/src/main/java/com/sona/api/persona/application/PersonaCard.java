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

    /**
     * 읽고 메모할 때 쓰는 소개 글: 기본 소개 + 메모 정리 습관 (용어 이해 단계별).
     * 잘못된 내용을 넣지 않고 '무엇을 얼마나 적는지'만 다르게 한다 (EVIDENCE.md 8-10). 답할 때는 {@link #of} 를 쓴다.
     */
    public static String forReading(Persona p) {
        return of(p) + "\n메모 습관: " + memoHabit(p);
    }

    static String memoHabit(Persona p) {
        return switch (p.getFinancialLiteracy()) {
            case HIGH -> "본 글의 숫자·금액·기간·조건·예외를 빠짐없이 정확하게, 글자 수 한도를 거의 다 채워 항목별로 정리한다." + " 비슷한 항목끼리 헷갈리지 않게 구분해 적는다.";
            case MEDIUM -> "중요해 보이는 숫자와 조건 위주로 적고, 자잘한 예외는 일부 빠뜨린다.";
            case LOW -> "전체 인상 위주로 짧게 적고, 숫자나 조건은 대충 기억한다.";
        };
    }

    private static String literacyText(Persona p) {
        return switch (p.getFinancialLiteracy()) {
            case HIGH -> "보험 용어와 조건을 대체로 정확히 이해하는 편";
            case MEDIUM -> "보험 용어를 대략적으로만 아는 편";
            case LOW -> "보험 용어를 잘 모르고, 비슷한 일상 말로 짐작하는 편";
        };
    }
}
