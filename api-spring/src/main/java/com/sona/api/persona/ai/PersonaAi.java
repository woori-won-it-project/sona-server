package com.sona.api.persona.ai;

import java.util.List;

/**
 * 페르소나 실험에서 AI 가 하는 일. 실제 구현은 {@link LlmPersonaAi}(Claude), 개발·테스트용은 {@link MockPersonaAi}.
 * 채점은 AI 가 하지 않는다 (서버 코드가 보기 정답과 비교).
 */
public interface PersonaAi {

    /** 질문마다 3지선다 보기(정답 1 + 오해 2)와 정답을 담은 설명서 문구를 만든다 */
    List<GeneratedOptions> generateOptions(String guideText, List<QuestionBrief> questions);

    /** 설명서에서 일반 소비자가 모를 만한 보험 용어 */
    List<String> extractHardTerms(String guideText);

    /** 설명서를 바탕으로 한 설계사 판매 말투 (예외·조건은 빼거나 흐림) */
    String agentTalk(String guideText);

    /** 실제로 본 글만으로 메모를 남긴다 */
    Memo writeMemo(String personaCard, String pathName, String seenText, int memoBudget);

    /** 메모만 보고 질문마다 보기 하나를 고른다 ('모르겠다' 없음) */
    List<PersonaAnswer> answer(String personaCard, String memo, List<QuestionWithOptions> questions);

    record QuestionBrief(long questionId, String questionText, String referenceAnswer, String referenceReason) {}

    record GeneratedOptions(long questionId, String correct, List<WrongOption> wrong, List<String> keyPhrases) {}

    record WrongOption(String text, boolean critical) {}

    record Memo(String firstImpression, List<String> lines) {}

    record QuestionWithOptions(long questionId, String questionText, List<OptionView> options) {}

    record OptionView(String key, String text) {}

    record PersonaAnswer(long questionId, String choice, String reason) {}
}
