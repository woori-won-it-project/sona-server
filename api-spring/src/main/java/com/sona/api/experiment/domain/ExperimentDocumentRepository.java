package com.sona.api.experiment.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ExperimentDocumentRepository extends JpaRepository<ExperimentDocument, Long> {

    List<ExperimentDocument> findByExperimentId(Long experimentId);
}
