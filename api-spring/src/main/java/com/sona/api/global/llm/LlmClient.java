package com.sona.api.global.llm;

/**
 * LLM 호출 창구. 실제 호출 구현은 {@link ClaudeLlmClient} 한 곳뿐이다 (AGENTS 규칙: LLM 호출은 클라이언트 클래스 하나로).
 * 응답은 outputType(record) 모양의 JSON 으로 강제한다.
 */
public interface LlmClient {

    /**
     * @param purpose 로그용 이름 (예: persona_read). 프롬프트 원문은 로그에 남기지 않는다
     * @param deepThinking true 면 생각 기능을 켠다 (보기 만들기처럼 정확도가 중요한 작업)
     */
    <T> T call(String purpose, String prompt, Class<T> outputType, boolean deepThinking, long maxTokens);
}
