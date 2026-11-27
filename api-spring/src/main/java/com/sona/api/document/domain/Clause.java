package com.sona.api.document.domain;

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

/** 문서 분석에서 나눈 조항 하나 (예: 제11조 지급사유). */
@Getter
@Entity
@Table(name = "clauses")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Clause extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "document_id", nullable = false)
    private Document document;

    @Column(name = "clause_number", length = 50)
    private String clauseNumber;

    @Column(length = 255)
    private String title;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String content;

    @Column(name = "start_page", nullable = false)
    private Integer startPage;

    @Column(name = "end_page", nullable = false)
    private Integer endPage;

    /** 문서 안에서의 조항 순서 */
    @Column(name = "sequence", nullable = false)
    private Integer sequence;

    @Builder
    private Clause(
            Document document,
            String clauseNumber,
            String title,
            String content,
            Integer startPage,
            Integer endPage,
            Integer sequence) {
        this.document = document;
        this.clauseNumber = clauseNumber;
        this.title = title;
        this.content = content;
        this.startPage = startPage;
        this.endPage = endPage;
        this.sequence = sequence;
    }
}
