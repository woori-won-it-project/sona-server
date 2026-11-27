package com.sona.api.experiment.api;

import com.sona.api.experiment.domain.ExperimentStatus;
import com.sona.api.experiment.domain.ExperimentType;
import java.time.LocalDateTime;

/** api.md 21 */
public record ExperimentStatusResponse(
        Long experimentId,
        Long reviewId,
        ExperimentType experimentType,
        Integer roundNumber,
        ExperimentStatus status,
        LocalDateTime createdAt) {}
