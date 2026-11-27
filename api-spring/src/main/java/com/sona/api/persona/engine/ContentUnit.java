package com.sona.api.persona.engine;

import java.util.List;

/**
 * 내용 묶음: 질문 하나의 정답을 담은 설명서 문구들. 같은 내용이 여러 곳에 반복돼도 사람마다 '한 번만' 볼지 정하고,
 * 놓치면 그 문구가 나오는 문장을 모두 가린다 (파일럿 C안 v4).
 */
public record ContentUnit(String key, List<String> phrases) {

    public boolean appearsIn(String sentence) {
        String s = sentence.replace(" ", "");
        return phrases.stream()
                .map(p -> p.replace(" ", ""))
                .filter(p -> !p.isEmpty())
                .anyMatch(s::contains);
    }
}
