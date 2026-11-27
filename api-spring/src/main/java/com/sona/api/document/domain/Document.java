package com.sona.api.document.domain;

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

/** 올린 PDF 한 개. 상품설명서를 다시 올리면 version 이 1 늘어난 행이 새로 생긴다. */
@Getter
@Entity
@Table(name = "documents")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Document extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "review_id", nullable = false)
    private Review review;

    @Enumerated(EnumType.STRING)
    @Column(name = "document_type", nullable = false, length = 30)
    private DocumentType documentType;

    @Column(nullable = false)
    private Long version;

    @Column(name = "original_filename", nullable = false, length = 255)
    private String originalFilename;

    @Column(name = "s3_path", nullable = false, length = 1024)
    private String s3Path;

    @Builder
    private Document(Review review, DocumentType documentType, Long version, String originalFilename, String s3Path) {
        this.review = review;
        this.documentType = documentType;
        this.version = version;
        this.originalFilename = originalFilename;
        this.s3Path = s3Path;
    }
}
