package com.sona.api.experiment.domain;

import com.sona.api.global.entity.BaseCreatedEntity;
import com.sona.api.persona.domain.ReviewPersona;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** 읽기 메모 (spec 4.7.2): 페르소나가 설명서를 읽고 남긴 메모. 답할 때는 설명서 없이 이 메모만 본다. */
@Getter
@Entity
@Table(
        name = "reading_memos",
        uniqueConstraints = @UniqueConstraint(columnNames = {"experiment_id", "review_persona_id"}))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ReadingMemo extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "experiment_id", nullable = false)
    private Experiment experiment;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "review_persona_id", nullable = false)
    private ReviewPersona reviewPersona;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String memo;

    @Column(name = "first_impression", columnDefinition = "TEXT")
    private String firstImpression;

    @Builder
    private ReadingMemo(Experiment experiment, ReviewPersona reviewPersona, String memo, String firstImpression) {
        this.experiment = experiment;
        this.reviewPersona = reviewPersona;
        this.memo = memo;
        this.firstImpression = firstImpression;
    }
}
