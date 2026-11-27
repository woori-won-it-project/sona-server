package com.sona.api.experiment.api;

import com.sona.api.experiment.domain.ExperimentStatus;
import com.sona.api.experiment.domain.ExperimentType;

/** api.md 20. totalResponses = 페르소나 수 x 승인 질문 수 */
public record StartExperimentResponse(
        Long experimentId,
        Long reviewId,
        ExperimentType experimentType,
        Long parentExperimentId,
        Integer roundNumber,
        Long documentVersion,
        ExperimentStatus status,
        int totalResponses) {}
