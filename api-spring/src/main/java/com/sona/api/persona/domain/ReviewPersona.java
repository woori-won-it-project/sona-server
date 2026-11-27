package com.sona.api.persona.domain;

import com.sona.api.review.domain.Review;
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

/** 검수 하나에서 고른 페르소나. 첫 실험 이후에는 바꿀 수 없다. */
@Getter
@Entity
@Table(name = "review_personas", uniqueConstraints = @UniqueConstraint(columnNames = {"review_id", "persona_id"}))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ReviewPersona {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "review_id", nullable = false)
    private Review review;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "persona_id", nullable = false)
    private Persona persona;

    @Builder
    private ReviewPersona(Review review, Persona persona) {
        this.review = review;
        this.persona = persona;
    }
}
