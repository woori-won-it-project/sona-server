package com.sona.api.experiment.application;

import static org.assertj.core.api.Assertions.assertThat;

import com.sona.api.experiment.domain.GradingResult;
import java.util.List;
import org.junit.jupiter.api.Test;

class GraderTest {

    private final List<Grader.Option> options = List.of(
            new Grader.Option("A", "오해", false, true),
            new Grader.Option("B", "정답", true, false),
            new Grader.Option("C", "오해", false, false));

    @Test
    void 정답_보기면_CORRECT_아니면_INCORRECT() {
        assertThat(Grader.grade(options, "B")).isEqualTo(GradingResult.CORRECT);
        assertThat(Grader.grade(options, "A")).isEqualTo(GradingResult.INCORRECT);
    }

    @Test
    void 답을_못_받으면_UNDETERMINED() {
        assertThat(Grader.grade(options, null)).isEqualTo(GradingResult.UNDETERMINED);
        assertThat(Grader.grade(options, "D")).isEqualTo(GradingResult.UNDETERMINED);
    }
}
