package com.sona.api.experiment.api;

import com.sona.api.experiment.domain.GradingResult;
import com.sona.api.persona.domain.FinancialLiteracy;
import com.sona.api.question.domain.Answer;
import java.util.List;

/**
 * api.md 22. 페르소나 한 명의 응답 묶음.
 * 3지선다 응답은 selectedOption·selectedOptionText·critical 을 채우고 selectedAnswer 는 null.
 */
public record PersonaResponsesResponse(
        Long reviewPersonaId,
        String personaName,
        FinancialLiteracy financialLiteracy,
        String readingMemo,
        List<Item> responses) {

    public record Item(
            Long questionId,
            Answer selectedAnswer,
            String selectedOption,
            String selectedOptionText,
            Boolean critical,
            String responseReason,
            GradingResult gradingResult,
            Evidence evidence) {}

    public record Evidence(Long documentId, Integer sourcePage, String evidenceText) {}
}
