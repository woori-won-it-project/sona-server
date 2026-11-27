package com.sona.api.experiment.api;

import com.sona.api.experiment.domain.ExperimentType;
import jakarta.validation.constraints.NotNull;

/** api.md 20. 첫 실험이면 parentExperimentId 는 null */
public record StartExperimentRequest(@NotNull ExperimentType experimentType, Long parentExperimentId) {}
