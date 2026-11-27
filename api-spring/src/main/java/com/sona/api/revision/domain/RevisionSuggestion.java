package com.sona.api.revision.domain;

import com.sona.api.document.domain.Document;
import com.sona.api.experiment.domain.Experiment;
import com.sona.api.global.entity.BaseCreatedEntity;
import com.sona.api.question.domain.Question;
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

/** AI 가 만든 상품설명서 수정 제안. 실험 하나, 질문 하나에 한 개. */
@Getter
@Entity
@Table(
        name = "revision_suggestions",
        uniqueConstraints = @UniqueConstraint(columnNames = {"experiment_id", "question_id"}))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class RevisionSuggestion extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 고칠 문장이 있는 문서 (상품설명서) */
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "document_id", nullable = false)
    private Document document;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "question_id", nullable = false)
    private Question question;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "experiment_id", nullable = false)
    private Experiment experiment;

    @Column(name = "source_page")
    private Integer sourcePage;

    @Column(name = "original_text", nullable = false, columnDefinition = "TEXT")
    private String originalText;

    @Column(name = "suggested_text", nullable = false, columnDefinition = "TEXT")
    private String suggestedText;

    @Column(name = "revision_reason", nullable = false, columnDefinition = "TEXT")
    private String revisionReason;

    @Builder
    private RevisionSuggestion(
            Document document,
            Question question,
            Experiment experiment,
            Integer sourcePage,
            String originalText,
            String suggestedText,
            String revisionReason) {
        this.document = document;
        this.question = question;
        this.experiment = experiment;
        this.sourcePage = sourcePage;
        this.originalText = originalText;
        this.suggestedText = suggestedText;
        this.revisionReason = revisionReason;
    }
}
