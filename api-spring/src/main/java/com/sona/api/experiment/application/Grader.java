package com.sona.api.experiment.application;

import com.sona.api.experiment.domain.GradingResult;
import java.util.List;

/** 코드 채점 (spec 4.7.2): 고른 보기가 정답이면 CORRECT, 아니면 INCORRECT, 답을 못 받았으면 UNDETERMINED. LLM 을 쓰지 않는다. */
public final class Grader {

    private Grader() {}

    public record Option(String key, String text, boolean correct, boolean critical) {}

    public static GradingResult grade(List<Option> options, String choice) {
        if (choice == null) {
            return GradingResult.UNDETERMINED;
        }
        return options.stream()
                .filter(o -> o.key().equals(choice))
                .findFirst()
                .map(o -> o.correct() ? GradingResult.CORRECT : GradingResult.INCORRECT)
                .orElse(GradingResult.UNDETERMINED);
    }
}
