package com.sona.api.global.llm;

import com.anthropic.client.AnthropicClient;
import com.anthropic.client.okhttp.AnthropicOkHttpClient;
import com.anthropic.models.messages.MessageCreateParams;
import com.anthropic.models.messages.StructuredMessageCreateParams;
import com.anthropic.models.messages.ThinkingConfigAdaptive;
import com.anthropic.models.messages.ThinkingConfigDisabled;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/**
 * Claude API 호출 (sona.llm.provider=claude 일 때만). 파일럿에서 검증한 모델은 claude-haiku-5-5.
 * 응답 모델은 spec D6 에서 확정 전이라 설정(sona.llm.model)으로 바꿀 수 있게 둔다.
 */
@Slf4j
@Component
@ConditionalOnProperty(name = "sona.llm.provider", havingValue = "claude")
public class ClaudeLlmClient implements LlmClient {

    private final AnthropicClient client;
    private final String model;

    public ClaudeLlmClient(@Value("${sona.llm.api-key:}") String apiKey, @Value("${sona.llm.model}") String model) {
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalStateException("sona.llm.provider=claude 인데 ANTHROPIC_API_KEY 가 비어 있습니다.");
        }
        this.client =
                AnthropicOkHttpClient.builder().apiKey(apiKey).maxRetries(3).build();
        this.model = model;
    }

    @Override
    public <T> T call(String purpose, String prompt, Class<T> outputType, boolean deepThinking, long maxTokens) {
        MessageCreateParams.Builder builder =
                MessageCreateParams.builder().model(model).maxTokens(maxTokens).addUserMessage(prompt);
        if (deepThinking) {
            builder.thinking(ThinkingConfigAdaptive.builder().build());
        } else {
            builder.thinking(ThinkingConfigDisabled.builder().build());
        }
        StructuredMessageCreateParams<T> params =
                builder.outputConfig(outputType).build();

        long started = System.currentTimeMillis();
        try {
            T result = client.messages().create(params).content().stream()
                    .flatMap(block -> block.text().stream())
                    .map(text -> text.text())
                    .findFirst()
                    .orElseThrow(() -> new LlmCallException(purpose + ": 응답에 글이 없습니다."));
            log.info("LLM 호출 완료 purpose={} model={} {}ms", purpose, model, System.currentTimeMillis() - started);
            return result;
        } catch (LlmCallException e) {
            throw e;
        } catch (RuntimeException e) {
            throw new LlmCallException(purpose + ": LLM 호출 실패", e);
        }
    }
}
