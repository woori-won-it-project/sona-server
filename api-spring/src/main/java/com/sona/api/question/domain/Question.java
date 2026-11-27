package com.sona.api.question.domain;

import com.sona.api.global.entity.BaseTimeEntity;
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
import java.time.LocalDateTime;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** 검증 질문 하나와 그 기준답안. */
@Getter
@Entity
@Table(name = "questions")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Question extends BaseTimeEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "review_id", nullable = false)
    private Review review;

    /** 질문 짧은 제목. ERD 에는 있지만 지금 API 에는 노출하지 않는다. */
    @Column(length = 100)
    private String title;

    @Enumerated(EnumType.STRING)
    @Column(name = "source_type", nullable = false, length = 30)
    private QuestionSourceType sourceType;

    @Column(name = "question_text", nullable = false, columnDefinition = "TEXT")
    private String questionText;

    @Column(name = "generation_reason", columnDefinition = "TEXT")
    private String generationReason;

    /** 기준답안: YES 또는 NO. 아직 없으면 null */
    @Enumerated(EnumType.STRING)
    @Column(name = "reference_answer", length = 10)
    private Answer referenceAnswer;

    @Column(name = "reference_answer_reason", columnDefinition = "TEXT")
    private String referenceAnswerReason;

    /** 정답을 담은 설명서 문구 (줄바꿈 구분). 3지선다 보기를 만들 때 함께 만든다. 페르소나가 이 내용을 놓치는지 볼 때 쓴다 */
    @Column(name = "key_phrases", columnDefinition = "TEXT")
    private String keyPhrases;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private QuestionStatus status = QuestionStatus.DRAFT;

    @Column(name = "approved_at")
    private LocalDateTime approvedAt;

    @Builder
    private Question(Review review, QuestionSourceType sourceType, String questionText, String generationReason) {
        this.review = review;
        this.sourceType = sourceType;
        this.questionText = questionText;
        this.generationReason = generationReason;
    }

    public void assignKeyPhrases(String keyPhrases) {
        this.keyPhrases = keyPhrases;
    }
}
