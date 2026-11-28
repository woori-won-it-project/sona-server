package com.sona.api.persona.engine;

import static org.assertj.core.api.Assertions.assertThat;

import com.sona.api.persona.domain.Disposition;
import com.sona.api.persona.domain.FinancialLiteracy;
import java.util.List;
import org.junit.jupiter.api.Test;

class PersonaReaderTest {

    private static final String GUIDE = "이 보험은 암 주요치료를 받으면 치료비를 드리는 갱신형 보험입니다.\n"
            + "암 주요치료비는 연간 1회, 최대 10회까지 1,000만원을 지급합니다.\n"
            + "다만 가입 후 1년이 지나기 전에 지급사유가 생기면 50%인 500만원을 지급합니다.\n"
            + "호르몬 관련 치료제를 쓰는 치료는 암 주요치료에서 제외합니다.\n"
            + "갱신할 때 보험료가 인상될 수 있습니다.";
    private static final List<String> TERMS = List.of("암 주요치료", "호르몬 관련 치료제", "갱신형");

    @Test
    void 같은_사람이면_언제나_같은_글을_본다() {
        var p = new PersonaProfile(7, FinancialLiteracy.MEDIUM, 0.5, Disposition.CAUTIOUS);
        assertThat(PersonaReader.read(p, GUIDE, List.of(), TERMS))
                .isEqualTo(PersonaReader.read(p, GUIDE, List.of(), TERMS));
    }

    @Test
    void 용어_이해_하는_60자가_넘는_문장이_잘린다() {
        String longSentence = "가".repeat(90) + "는 보장하지 않습니다.";
        var p = new PersonaProfile(1, FinancialLiteracy.LOW, 1.0, Disposition.CAUTIOUS);
        var r = PersonaReader.read(p, longSentence, List.of(), List.of());
        assertThat(r.cutSentences()).isEqualTo(1);
        assertThat(r.seenText()).hasSize(61).doesNotContain("보장하지");
    }

    @Test
    void 용어_이해_하는_어려운_용어를_대부분_가린다() {
        // 가릴 확률 70%: 여러 사람의 평균이 절반을 넘어야 한다
        int masked = 0;
        int total = 0;
        for (long seed = 1; seed <= 30; seed++) {
            var p = new PersonaProfile(seed, FinancialLiteracy.LOW, 1.0, Disposition.CAUTIOUS);
            masked +=
                    PersonaReader.read(p, GUIDE, List.of(), TERMS).maskedTerms().size();
            total += TERMS.size();
        }
        assertThat((double) masked / total).isBetween(0.5, 0.9);
    }

    @Test
    void 용어_이해_상은_자르지도_가리지도_않는다() {
        var p = new PersonaProfile(1, FinancialLiteracy.HIGH, 1.0, Disposition.CAUTIOUS);
        var r = PersonaReader.read(p, GUIDE, List.of(), TERMS);
        assertThat(r.cutSentences()).isZero();
        assertThat(r.maskedTerms()).isEmpty();
    }

    @Test
    void 놓친_내용은_나오는_문장이_모두_빠진다() {
        var unit = new ContentUnit("q1", List.of("50%"));
        // 꼼꼼함 0 이면 내용을 볼 확률 0.2: 여러 사람 중 놓친 사람이 있어야 하고, 놓친 사람의 글에는 그 문구가 없어야 한다
        int missedPeople = 0;
        for (long seed = 1; seed <= 30; seed++) {
            var p = new PersonaProfile(seed, FinancialLiteracy.HIGH, 0.0, Disposition.OPTIMISTIC);
            var r = PersonaReader.read(p, GUIDE, List.of(unit), List.of());
            if (r.missedUnits().contains("q1")) {
                missedPeople++;
                assertThat(r.seenText()).doesNotContain("50%");
            }
        }
        assertThat(missedPeople).isPositive();
    }

    @Test
    void 메모_한도는_꼼꼼함에_따라_200자에서_600자_그리고_이해_단계_배수() {
        assertThat(PersonaReader.memoBudget(0.1, FinancialLiteracy.LOW)).isEqualTo(200);
        assertThat(PersonaReader.memoBudget(0.9, FinancialLiteracy.LOW)).isEqualTo(600);
        assertThat(PersonaReader.memoBudget(0.525, FinancialLiteracy.LOW)).isEqualTo(400);
        // 용어 이해 단계 배수: 중 x1.6, 상 x3.0
        assertThat(PersonaReader.memoBudget(0.525, FinancialLiteracy.MEDIUM)).isEqualTo(640);
        assertThat(PersonaReader.memoBudget(0.525, FinancialLiteracy.HIGH)).isEqualTo(1200);
    }

    @Test
    void 메모는_한도를_넘으면_코드가_자른다() {
        var cut = PersonaReader.cutMemo(List.of("가".repeat(100), "나".repeat(100)), 150);
        assertThat(String.join("", cut).replace("…", "")).hasSize(150);
    }
}
