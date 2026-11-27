package com.sona.api.experiment.domain;

import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ExperimentRepository extends JpaRepository<Experiment, Long> {

    List<Experiment> findByReviewIdAndStatusOrderByRoundNumberAsc(Long reviewId, ExperimentStatus status);

    boolean existsByReviewIdAndStatus(Long reviewId, ExperimentStatus status);

    /** 실패하지 않은 실험이 하나라도 있으면 질문·페르소나가 잠긴다 */
    boolean existsByReviewIdAndStatusNot(Long reviewId, ExperimentStatus status);

    boolean existsByReviewIdAndParentExperimentIsNullAndStatusNot(Long reviewId, ExperimentStatus status);

    Optional<Experiment> findTopByReviewIdAndStatusOrderByRoundNumberDesc(Long reviewId, ExperimentStatus status);
}
