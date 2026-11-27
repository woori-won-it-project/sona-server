package com.sona.api.global.llm;

/** LLM 호출이 실패하거나 응답이 비었을 때. 실험은 FAILED 로 끝난다. */
public class LlmCallException extends RuntimeException {

    public LlmCallException(String message) {
        super(message);
    }

    public LlmCallException(String message, Throwable cause) {
        super(message, cause);
    }
}
