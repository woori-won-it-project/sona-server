package com.sona.api.experiment.domain;

import com.sona.api.global.entity.BaseCreatedEntity;
import com.sona.api.review.domain.Review;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 실험 한 번. 첫 실험이면 parentExperiment 가 null, 재실험이면 바로 이전 실험을 가리킨다.
 * experimentType(INITIAL / RERUN) 은 컬럼이 없고 {@link #isInitial()} 로 판단한다.
 */
@Getter
@Entity
@Table(name = "experiments")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Experiment extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "review_id", nullable = false)
    private Review review;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "parent_experiment_id")
    private Experiment parentExperiment;

    @Column(name = "round_number", nullable = false)
    private Integer roundNumber;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    private ExperimentStatus status = ExperimentStatus.RUNNING;

    @Builder
    private Experiment(Review review, Experiment parentExperiment, Integer roundNumber) {
        this.review = review;
        this.parentExperiment = parentExperiment;
        this.roundNumber = roundNumber;
    }

    public boolean isInitial() {
        return parentExperiment == null;
    }

    public void complete() {
        this.status = ExperimentStatus.COMPLETED;
    }

    public void fail() {
        this.status = ExperimentStatus.FAILED;
    }
}
