package com.sona.api.persona.domain;

/**
 * personas.info_path: 상품 정보를 어디서 얻는지. 페르소나는 약관을 보지 않는다 (spec 4.7).
 * AGENT_TALK 은 상품설명서를 바탕으로 AI 가 만든 설계사 판매 말투(예외·조건은 빼거나 흐림)를 듣는다.
 */
public enum InfoPath {
    GUIDE("상품설명서를 직접 읽음"),
    AGENT_TALK("설계사 설명을 들음");

    private final String label;

    InfoPath(String label) {
        this.label = label;
    }

    public String label() {
        return label;
    }
}
