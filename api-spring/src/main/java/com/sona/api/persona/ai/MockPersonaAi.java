package com.sona.api.persona.ai;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/**
 * AI 를 부르지 않는 가짜 구현 (기본값, mock 프로필·테스트용). 같은 입력이면 언제나 같은 결과를 낸다.
 * 결과는 화면·흐름 확인용일 뿐 실험 의미는 없다.
 */
@Component
@ConditionalOnProperty(name = "sona.llm.provider", havingValue = "mock", matchIfMissing = true)
public class MockPersonaAi implements PersonaAi {

    private static final List<String> SAMPLE_TERMS = List.of("암 주요치료", "호르몬 관련 치료제", "보험요율", "해약환급금", "갱신형");

    @Override
    public List<GeneratedOptions> generateOptions(String guideText, List<QuestionBrief> questions) {
        List<GeneratedOptions> out = new ArrayList<>();
        for (QuestionBrief q : questions) {
            List<String> phrases = Arrays.stream(q.questionText().split("\\s+"))
                    .map(w -> w.replaceAll("[^가-힣0-9,%]", ""))
                    .filter(w -> w.length() >= 3 && guideText.contains(w))
                    .limit(2)
                    .toList();
            out.add(new GeneratedOptions(
                    q.questionId(),
                    "[정답] " + q.referenceAnswer(),
                    List.of(new WrongOption("[오해] 더 받는다고 믿음", true), new WrongOption("[오해] 덜 받는다고 믿음", false)),
                    phrases));
        }
        return out;
    }

    @Override
    public List<String> extractHardTerms(String guideText) {
        return SAMPLE_TERMS.stream().filter(guideText::contains).toList();
    }

    @Override
    public String agentTalk(String guideText) {
        String first = guideText.lines().findFirst().orElse("");
        return first + " 자세한 조건은 약관에 있어요.";
    }

    @Override
    public Memo writeMemo(String personaCard, String pathName, String seenText, int memoBudget) {
        List<String> lines = seenText.lines().filter(l -> !l.isBlank()).limit(5).toList();
        return new Memo("(모의 응답) " + pathName, lines);
    }

    @Override
    public List<PersonaAnswer> answer(String personaCard, String memo, List<QuestionWithOptions> questions) {
        return questions.stream()
                .map(q -> {
                    int pick = (int)
                            ((q.questionId() + memo.length()) % q.options().size());
                    return new PersonaAnswer(
                            q.questionId(), q.options().get(pick).key(), "(모의 응답) 메모를 보고 골랐습니다.");
                })
                .toList();
    }
}
