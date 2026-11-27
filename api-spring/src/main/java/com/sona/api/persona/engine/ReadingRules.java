package com.sona.api.persona.engine;

import com.sona.api.persona.domain.Disposition;
import java.util.List;
import java.util.regex.Pattern;

/**
 * 문장 하나가 읽힐 확률 (파일럿 config/reading_rules.yaml, 모두 가정값).
 * 읽힘 확률 = (0.55 + 0.25 x 꼼꼼함) x 위치 x 형식 x 종류, 최대 1.
 */
public final class ReadingRules {

    static final double BUDGET_BASE = 0.55;
    static final double BUDGET_SLOPE = 0.25;
    /** 글의 앞 30% 는 위치 가중치 1.0, 끝으로 갈수록 0.7 까지 줄어든다 */
    static final double POSITION_FULL_UNTIL = 0.30;

    static final double POSITION_END_FACTOR = 0.70;
    static final double HEADING_FACTOR = 1.3;
    /** 괄호 안 문장·각주·※ 문장 */
    static final double ASIDE_FACTOR = 0.5;

    static final double COVERAGE_FACTOR = 1.2;
    static final double COVERAGE_OPTIMISTIC_FACTOR = 1.4;
    static final double EXCEPTION_BASE = 0.6;
    static final double EXCEPTION_SLOPE = 0.4;
    static final double EXCEPTION_CAUTIOUS_EXTRA = 1.2;

    static final List<String> COVERAGE_WORDS = List.of("지급", "보장", "드립니다", "드려요", "받을 수", "나옵니다");
    static final List<String> EXCEPTION_WORDS = List.of("다만", "제외", "지급하지", "감액", "면책", "않습니다", "한하여", "경우에 한", "보장하지");

    private static final Pattern HEADING_SENTENCE = Pattern.compile("^제\\s*\\d+\\s*조\\s*【[^】]+】$");
    private static final Pattern BRACKET_HEAD = Pattern.compile("^\\[[^\\]]+\\].*");

    private ReadingRules() {}

    public static double probability(int index, int total, String sentence, double diligence, Disposition disposition) {
        double budget = BUDGET_BASE + BUDGET_SLOPE * diligence;
        double pos = total > 1 ? (double) index / (total - 1) : 0.0;
        double position = pos <= POSITION_FULL_UNTIL
                ? 1.0
                : 1.0 - (1.0 - POSITION_END_FACTOR) * (pos - POSITION_FULL_UNTIL) / (1.0 - POSITION_FULL_UNTIL);
        double form = switch (format(sentence)) {
            case HEADING -> HEADING_FACTOR;
            case ASIDE -> ASIDE_FACTOR;
            case NORMAL -> 1.0;
        };
        double kind = switch (kind(sentence)) {
            case COVERAGE -> disposition == Disposition.OPTIMISTIC ? COVERAGE_OPTIMISTIC_FACTOR : COVERAGE_FACTOR;
            case EXCEPTION ->
                (EXCEPTION_BASE + EXCEPTION_SLOPE * diligence)
                        * (disposition == Disposition.CAUTIOUS ? EXCEPTION_CAUTIOUS_EXTRA : 1.0);
            case OTHER -> 1.0;
        };
        return Math.min(1.0, budget * position * form * kind);
    }

    enum Format {
        HEADING,
        ASIDE,
        NORMAL
    }

    enum Kind {
        COVERAGE,
        EXCEPTION,
        OTHER
    }

    static Format format(String s) {
        boolean heading = HEADING_SENTENCE.matcher(s).matches()
                || s.endsWith("?")
                || (s.startsWith("[") && s.endsWith("]"))
                || (BRACKET_HEAD.matcher(s).matches() && s.length() < 40)
                || (s.startsWith("※") && s.length() <= 25);
        if (heading) {
            return Format.HEADING;
        }
        if (s.startsWith("(") || s.startsWith("※") || s.startsWith("（")) {
            return Format.ASIDE;
        }
        return Format.NORMAL;
    }

    /** 예외 문장이 우선 (예: "다만 ... 50%를 지급") */
    static Kind kind(String s) {
        if (EXCEPTION_WORDS.stream().anyMatch(s::contains)) {
            return Kind.EXCEPTION;
        }
        if (COVERAGE_WORDS.stream().anyMatch(s::contains)) {
            return Kind.COVERAGE;
        }
        return Kind.OTHER;
    }
}
