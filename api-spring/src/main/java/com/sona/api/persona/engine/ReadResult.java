package com.sona.api.persona.engine;

import java.util.List;

/**
 * 한 페르소나가 실제로 본 글과, 무엇을 덜어 냈는지 기록.
 *
 * @param seenText 실제로 본 글 (놓친 문장 빠짐, 긴 문장 잘림, 어려운 용어 □□)
 * @param memoBudget 메모 글자 수 한도
 */
public record ReadResult(
        String seenText,
        int readCount,
        int totalSentences,
        List<String> missedUnits,
        int cutSentences,
        List<String> maskedTerms,
        int memoBudget) {}
