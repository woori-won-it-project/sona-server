package com.sona.api.persona.engine;

import com.sona.api.persona.domain.FinancialLiteracy;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;

/**
 * 페르소나가 글을 읽는 규칙 (spec 4.7.1 · 4.7.2, 파일럿 c_tune.py v5).
 * 잘못된 믿음을 넣지 않고 정보를 '덜어 내기'만 한다. 무엇을 믿을지는 AI 가 남은 정보로 짐작한다.
 *
 * <ol>
 *   <li>문장 읽기: 꼼꼼함·위치·형식·종류로 정한 확률로 문장마다 읽을지 정한다 ({@link ReadingRules})
 *   <li>내용 단위 놓치기: 질문별 핵심 문구를 볼 확률 = 0.2 + 꼼꼼함 + (상 0.5 · 중 0.3 · 하 0). 놓치면 그 문구가 든 문장을 모두 가린다
 *   <li>긴 문장 자르기: 용어 이해 하 60자, 중 140자, 상 그대로
 *   <li>어려운 용어 가리기: 하 70%, 중 20%, 상 없음 → □□
 *   <li>메모 글자 수: 꼼꼼함 0.30 이하 200자 ~ 0.75 이상 600자, 여기에 상 x3.0 · 중 x1.6 · 하 x1.0
 * </ol>
 *
 * 숫자는 모두 파일럿의 가정값이다. 목표 정답률(하 40 · 중 60 · 상 80%대)에 맞춰 2026-11-28 조정했다
 * (persona-pilot/EVIDENCE.md 8-10). 메모 정리 습관은 읽기 지시문에 붙는다 ({@code PersonaCard.forReading}).
 */
public final class PersonaReader {

    static final double UNIT_BASE = 0.2;
    static final double DILIGENCE_LOW = 0.30;
    static final double DILIGENCE_HIGH = 0.75;
    static final int MEMO_CHARS_MIN = 200;
    static final int MEMO_CHARS_MAX = 600;
    static final String MASK = "□□";
    static final String CUT_MARK = "…";

    private PersonaReader() {}

    public static ReadResult read(PersonaProfile p, String text, List<ContentUnit> units, List<String> hardTerms) {
        List<String> sentences = SentenceSplitter.split(text);
        int n = sentences.size();
        boolean[] read = new boolean[n];

        // 1. 문장 읽기 (첫 문장은 늘 읽는다)
        for (int i = 0; i < n; i++) {
            String s = sentences.get(i);
            double prob = i == 0 ? 1.0 : ReadingRules.probability(i, n, s, p.diligence(), p.disposition());
            read[i] = SeededRandom.next(p.seed(), "READ:" + s) < prob;
        }

        // 2. 내용 단위 놓치기
        double catchProb = Math.min(1.0, UNIT_BASE + p.diligence() + unitBonus(p.literacy()));
        List<String> missed = new ArrayList<>();
        for (ContentUnit unit : units) {
            if (SeededRandom.next(p.seed(), "UNIT:" + unit.key()) < catchProb) {
                continue;
            }
            missed.add(unit.key());
            for (int i = 0; i < n; i++) {
                if (read[i] && unit.appearsIn(sentences.get(i))) {
                    read[i] = false;
                }
            }
        }

        // 3. 긴 문장 자르기
        Integer limit = sentenceChars(p.literacy());
        int cut = 0;
        int readCount = 0;
        List<String> seen = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            if (!read[i]) {
                continue;
            }
            readCount++;
            String s = sentences.get(i);
            if (limit != null && s.length() > limit) {
                s = s.substring(0, limit) + CUT_MARK;
                cut++;
            }
            seen.add(s);
        }

        // 4. 어려운 용어 가리기 (긴 용어부터: 부분 겹침 방지)
        String seenText = String.join("\n", seen);
        double rate = maskRate(p.literacy());
        List<String> masked = new ArrayList<>();
        List<String> terms = new ArrayList<>(new LinkedHashSet<>(hardTerms));
        terms.sort(Comparator.comparingInt(String::length).reversed());
        for (String term : terms) {
            if (term.isBlank() || SeededRandom.next(p.seed(), "MASK:" + term) >= rate) {
                continue;
            }
            boolean hit = false;
            for (String variant : new LinkedHashSet<>(List.of(term, term.replace(" ", "")))) {
                if (seenText.contains(variant)) {
                    seenText = seenText.replace(variant, MASK);
                    hit = true;
                }
            }
            if (hit) {
                masked.add(term);
            }
        }

        return new ReadResult(seenText, readCount, n, missed, cut, masked, memoBudget(p.diligence(), p.literacy()));
    }

    /** 메모 글자 수 한도: 꼼꼼함 0.30 이하 200자 ~ 0.75 이상 600자(사이는 비례) x 용어 이해 단계 배수 */
    public static int memoBudget(double diligence, FinancialLiteracy literacy) {
        double t = Math.min(1.0, Math.max(0.0, (diligence - DILIGENCE_LOW) / (DILIGENCE_HIGH - DILIGENCE_LOW)));
        return (int) Math.round((MEMO_CHARS_MIN + t * (MEMO_CHARS_MAX - MEMO_CHARS_MIN)) * memoScale(literacy));
    }

    static double memoScale(FinancialLiteracy literacy) {
        return switch (literacy) {
            case LOW -> 1.0;
            case MEDIUM -> 1.6;
            case HIGH -> 3.0;
        };
    }

    /** 핵심 내용을 볼 확률에 더하는 값: 이해 수준이 높을수록 핵심을 알아본다 */
    static double unitBonus(FinancialLiteracy literacy) {
        return switch (literacy) {
            case LOW -> 0.0;
            case MEDIUM -> 0.3;
            case HIGH -> 0.5;
        };
    }

    /** AI 가 한도보다 많이 써도 코드가 앞에서부터 한도만큼만 남긴다 */
    public static List<String> cutMemo(List<String> memo, int budget) {
        List<String> out = new ArrayList<>();
        int used = 0;
        for (String m : memo) {
            if (used >= budget) {
                break;
            }
            int room = budget - used;
            out.add(m.length() <= room ? m : m.substring(0, room) + CUT_MARK);
            used += Math.min(m.length(), room);
        }
        return out;
    }

    /** 용어 이해 단계별로 한 문장에서 읽을 수 있는 글자 수. null 이면 끝까지 */
    static Integer sentenceChars(FinancialLiteracy literacy) {
        return switch (literacy) {
            case LOW -> 60;
            case MEDIUM -> 140;
            case HIGH -> null;
        };
    }

    static double maskRate(FinancialLiteracy literacy) {
        return switch (literacy) {
            case LOW -> 0.7;
            case MEDIUM -> 0.2;
            case HIGH -> 0.0;
        };
    }
}
