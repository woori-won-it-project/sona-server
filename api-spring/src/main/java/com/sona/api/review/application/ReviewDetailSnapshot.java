package com.sona.api.review.application;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.sona.api.document.domain.Document;
import com.sona.api.document.domain.DocumentType;
import com.sona.api.review.domain.ReviewStatus;
import com.sona.api.review.domain.ReviewStep;
import java.time.LocalDateTime;
import java.util.List;

/** 소유권 확인을 마친 내부 조회 결과. 문서 크기는 스토리지 메타데이터 조회에서 결합한다. */
public record ReviewDetailSnapshot(
        Long reviewId,
        String title,
        ReviewStatus status,
        ReviewStep currentStep,
        List<DocumentMetadata> documents,
        LocalDateTime createdAt,
        LocalDateTime updatedAt,
        LocalDateTime completedAt) {

    public record DocumentMetadata(
            Long documentId,
            DocumentType documentType,
            String filename,
            Long version,
            @JsonIgnore String s3Path) {

        static DocumentMetadata from(Document document) {
            return new DocumentMetadata(
                    document.getId(),
                    document.getDocumentType(),
                    document.getOriginalFilename(),
                    document.getVersion(),
                    document.getS3Path());
        }
    }
}
