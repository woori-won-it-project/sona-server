package com.sona.api.global.llm;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/** resources/prompts/{name}_v1.md 를 읽어 {{key}} 자리에 값을 넣는다. */
@Component
public class PromptTemplates {

    private static final String VERSION = "v1";
    private final Map<String, String> cache = new ConcurrentHashMap<>();

    public String render(String name, Map<String, String> values) {
        String text = cache.computeIfAbsent(name, this::load);
        for (Map.Entry<String, String> e : values.entrySet()) {
            text = text.replace("{{" + e.getKey() + "}}", e.getValue() == null ? "" : e.getValue());
        }
        return text;
    }

    private String load(String name) {
        String path = "prompts/" + name + "_" + VERSION + ".md";
        try (InputStream in = new ClassPathResource(path).getInputStream()) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException("프롬프트 파일을 읽지 못했습니다: " + path, e);
        }
    }
}
