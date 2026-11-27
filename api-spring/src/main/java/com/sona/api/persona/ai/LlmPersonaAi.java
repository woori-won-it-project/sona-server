package com.sona.api.persona.ai;

import com.sona.api.global.llm.LlmClient;
import com.sona.api.global.llm.PromptTemplates;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/** Claude 로 페르소나 실험의 AI 작업을 한다. 프롬프트는 resources/prompts/*_v1.md */
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "sona.llm.provider", havingValue = "claude")
public class LlmPersonaAi implements PersonaAi {

    private final LlmClient llm;
    private final PromptTemplates prompts;

    // structured output 모양 (Claude 응답을 이 record 로 받는다)
    public record OptionsOutput(List<GeneratedOptions> items) {}

    public record TermsOutput(List<String> terms) {}

    public record TalkOutput(String talk) {}

    public enum Choice {
        A,
        B,
        C
    }

    public record AnswerItem(long questionId, Choice choice, String reason) {}

    public record AnswersOutput(List<AnswerItem> answers) {}

    @Override
    public List<GeneratedOptions> generateOptions(String guideText, List<QuestionBrief> questions) {
        String block = questions.stream()
                .map(q -> q.questionId() + ". " + q.questionText() + "\n   기준 답: " + q.referenceAnswer() + " - "
                        + q.referenceReason())
                .collect(Collectors.joining("\n"));
        String prompt = prompts.render("question_options", Map.of("questions", block, "guide", guideText));
        return llm.call("question_options", prompt, OptionsOutput.class, true, 16000)
                .items();
    }

    @Override
    public List<String> extractHardTerms(String guideText) {
        String prompt = prompts.render("guide_hard_terms", Map.of("guide", guideText));
        return llm.call("guide_hard_terms", prompt, TermsOutput.class, false, 2000)
                .terms();
    }

    @Override
    public String agentTalk(String guideText) {
        String prompt = prompts.render("persona_agent_talk", Map.of("guide", guideText));
        return llm.call("persona_agent_talk", prompt, TalkOutput.class, false, 2000)
                .talk();
    }

    @Override
    public Memo writeMemo(String personaCard, String pathName, String seenText, int memoBudget) {
        String prompt = prompts.render(
                "persona_read",
                Map.of(
                        "card", personaCard,
                        "pathName", pathName,
                        "budget", String.valueOf(memoBudget),
                        "seen", seenText));
        return llm.call("persona_read", prompt, Memo.class, false, 4000);
    }

    @Override
    public List<PersonaAnswer> answer(String personaCard, String memo, List<QuestionWithOptions> questions) {
        String block = questions.stream()
                .map(q -> q.questionId() + ". " + q.questionText() + "\n"
                        + q.options().stream()
                                .map(o -> "   " + o.key() + ". " + o.text())
                                .collect(Collectors.joining("\n")))
                .collect(Collectors.joining("\n"));
        String prompt = prompts.render("persona_answer", Map.of("card", personaCard, "memo", memo, "questions", block));
        return llm.call("persona_answer", prompt, AnswersOutput.class, false, 4000).answers().stream()
                .map(a -> new PersonaAnswer(
                        a.questionId(), a.choice() == null ? null : a.choice().name(), a.reason()))
                .toList();
    }
}
