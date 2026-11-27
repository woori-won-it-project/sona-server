package com.sona.api.experiment.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ExperimentRepository extends JpaRepository<Experiment, Long> {

    List<Experiment> findByReviewIdAndStatusOrderByRoundNumberAsc(Long reviewId, ExperimentStatus status);

    boolean existsByReviewIdAndStatus(Long reviewId, ExperimentStatus status);
}
