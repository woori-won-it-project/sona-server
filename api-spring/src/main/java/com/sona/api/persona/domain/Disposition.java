package com.sona.api.persona.domain;

/** personas.disposition: 애매할 때의 판단 태도. 50:50 (spec 4.7.1) */
public enum Disposition {
    OPTIMISTIC("애매한 부분이 있으면 보장되는 쪽으로 받아들이는 편입니다."),
    CAUTIOUS("애매한 부분이 있으면 보장되지 않을 수도 있다고 생각하는 편입니다.");

    private final String sentence;

    Disposition(String sentence) {
        this.sentence = sentence;
    }

    public String sentence() {
        return sentence;
    }
}
