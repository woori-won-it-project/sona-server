package com.sona.api.persona.engine;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** 설명서 글을 문장으로 나눈다 (파일럿 04_build_prompts.split_sentences 와 같은 규칙). */
public final class SentenceSplitter {

    /** "제7조 【...】 본문" 은 조 제목과 본문을 나눈다 */
    private static final Pattern HEADING = Pattern.compile("^(제\\s*\\d+\\s*조\\s*【[^】]+】)\\s*");

    /** 설명서 안내문 번호 */
    private static final String NOTE_MARK = "❶❷❸❹❺❻❼❽❾❿⓫⓬⓭⓮⓯";

    /** "다. 연간: ..." 같은 목 번호에서 자르지 않도록, 앞에 한글이 한 글자 더 있을 때만 자른다 */
    private static final Pattern SENT_END =
            Pattern.compile("(?<=[가-힣][다요음함됨임원])\\.\\s+|(?<=\\?)\\s+|\\s+(?=[" + NOTE_MARK + "]\\s)");

    private static final Pattern ENDS_WITH_EOMI = Pattern.compile("[다요음함됨임원]$");

    private SentenceSplitter() {}

    public static List<String> split(String text) {
        List<String> out = new ArrayList<>();
        if (text == null) {
            return out;
        }
        for (String rawLine : text.split("\\R")) {
            String line = rawLine.strip();
            if (line.isEmpty()) {
                continue;
            }
            Matcher m = HEADING.matcher(line);
            if (m.find()) {
                out.add(m.group(1));
                line = line.substring(m.end());
                if (line.isEmpty()) {
                    continue;
                }
            }
            List<String> parts = Arrays.stream(SENT_END.split(line))
                    .map(String::strip)
                    .filter(p -> !p.isEmpty())
                    .toList();
            for (int i = 0; i < parts.size(); i++) {
                String p = parts.get(i);
                // 나눌 때 빠진 마침표를 되돌린다
                if (i < parts.size() - 1 && ENDS_WITH_EOMI.matcher(p).find()) {
                    p += ".";
                }
                out.add(p);
            }
        }
        return out;
    }
}
