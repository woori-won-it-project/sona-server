package com.sona.api.experiment.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ExperimentResponseRepository extends JpaRepository<ExperimentResponse, Long> {

    List<ExperimentResponse> findByExperimentId(Long experimentId);
}
