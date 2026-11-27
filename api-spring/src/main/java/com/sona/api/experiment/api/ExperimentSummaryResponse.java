package com.sona.api.experiment.api;

import com.sona.api.experiment.domain.ExperimentType;
import java.time.LocalDateTime;

/** api.md 23. misunderstandingRate = (오답 + 판단 불가) / 전체 x 100, 소수 둘째 자리 */
public record ExperimentSummaryResponse(
        Long experimentId,
        ExperimentType experimentType,
        Long parentExperimentId,
        Integer roundNumber,
        Long documentVersion,
        double misunderstandingRate,
        LocalDateTime createdAt) {}
