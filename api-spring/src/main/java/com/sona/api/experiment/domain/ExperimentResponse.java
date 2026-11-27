package com.sona.api.experiment.domain;

import com.sona.api.document.domain.Document;
import com.sona.api.global.entity.BaseCreatedEntity;
import com.sona.api.persona.domain.ReviewPersona;
import com.sona.api.question.domain.Answer;
import com.sona.api.question.domain.Question;
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
import jakarta.persistence.UniqueConstraint;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** 실험 1회 x 페르소나 1명 x 질문 1개의 응답과 채점 결과. 리포트 집계의 기본 단위. */
@Getter
@Entity
@Table(
        name = "experiment_responses",
        uniqueConstraints = @UniqueConstraint(columnNames = {"experiment_id", "review_persona_id", "question_id"}))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ExperimentResponse extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "experiment_id", nullable = false)
    private Experiment experiment;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "review_persona_id", nullable = false)
    private ReviewPersona reviewPersona;

    /** 페르소나가 답할 때 읽은 문서 (보통 그 실험의 상품설명서) */
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "document_id", nullable = false)
    private Document document;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "question_id", nullable = false)
    private Question question;

    @Enumerated(EnumType.STRING)
    @Column(name = "selected_answer", length = 10)
    private Answer selectedAnswer;

    /** 3지선다로 고른 보기 (A/B/C). 예/아니요 응답이면 null */
    @Column(name = "selected_option", length = 1)
    private String selectedOption;

    @Column(name = "response_reason", columnDefinition = "TEXT")
    private String responseReason;

    @Enumerated(EnumType.STRING)
    @Column(name = "grading_result", length = 20)
    private GradingResult gradingResult;

    @Column(name = "evidence_page")
    private Integer evidencePage;

    @Column(name = "evidence_text", columnDefinition = "TEXT")
    private String evidenceText;

    @Builder
    private ExperimentResponse(
            Experiment experiment,
            ReviewPersona reviewPersona,
            Document document,
            Question question,
            Answer selectedAnswer,
            String selectedOption,
            String responseReason,
            GradingResult gradingResult,
            Integer evidencePage,
            String evidenceText) {
        this.experiment = experiment;
        this.reviewPersona = reviewPersona;
        this.document = document;
        this.question = question;
        this.selectedAnswer = selectedAnswer;
        this.selectedOption = selectedOption;
        this.responseReason = responseReason;
        this.gradingResult = gradingResult;
        this.evidencePage = evidencePage;
        this.evidenceText = evidenceText;
    }

    /** 오해로 세는 응답인지: 오답 또는 판단 불가 */
    public boolean isMisunderstood() {
        return gradingResult == GradingResult.INCORRECT || gradingResult == GradingResult.UNDETERMINED;
    }
}
