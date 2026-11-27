package com.sona.api.persona.engine;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class SentenceSplitterTest {

    @Test
    void 마침표와_줄바꿈으로_나눈다() {
        var sentences = SentenceSplitter.split("암 진단 시 지급합니다. 다만 1년 내에는 50%를 지급합니다.\n갱신할 수 있습니다.");
        assertThat(sentences).containsExactly("암 진단 시 지급합니다.", "다만 1년 내에는 50%를 지급합니다.", "갱신할 수 있습니다.");
    }

    @Test
    void 목_번호는_자르지_않는다() {
        assertThat(SentenceSplitter.split("다. 연간: 매년 계약해당일부터 1년")).hasSize(1);
    }

    @Test
    void 조_제목과_본문을_나눈다() {
        assertThat(SentenceSplitter.split("제7조 【암 주요치료】 면역력 강화 치료는 제외합니다."))
                .containsExactly("제7조 【암 주요치료】", "면역력 강화 치료는 제외합니다.");
    }
}
