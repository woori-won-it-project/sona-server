package com.sona.api.question.domain;

import com.sona.api.document.domain.Clause;
import com.sona.api.global.entity.BaseCreatedEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
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
 * 질문의 근거. 약관 조항(clause) 또는 분쟁사례 청크(case_chunk) 중 하나 이상을 가리킨다.
 * case_chunk 는 데이터 담당 소유의 읽기 전용 테이블이라 Entity 없이 ID 만 저장한다.
 */
@Getter
@Entity
@Table(name = "question_evidences")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class QuestionEvidence extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "question_id", nullable = false)
    private Question question;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "clause_id")
    private Clause clause;

    @Column(name = "case_chunk_id")
    private Long caseChunkId;

    @Column(name = "source_page")
    private Integer sourcePage;

    @Column(name = "evidence_text", nullable = false, columnDefinition = "TEXT")
    private String evidenceText;

    @Builder
    private QuestionEvidence(
            Question question, Clause clause, Long caseChunkId, Integer sourcePage, String evidenceText) {
        this.question = question;
        this.clause = clause;
        this.caseChunkId = caseChunkId;
        this.sourcePage = sourcePage;
        this.evidenceText = evidenceText;
    }
}
