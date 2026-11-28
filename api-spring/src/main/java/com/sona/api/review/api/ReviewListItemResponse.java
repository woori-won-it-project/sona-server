package com.sona.api.review.api;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.sona.api.document.domain.DocumentType;
import com.sona.api.review.domain.ReviewRepository;
import com.sona.api.review.domain.ReviewStatus;
import com.sona.api.review.domain.ReviewStep;
import java.time.LocalDateTime;

public record ReviewListItemResponse(
        Long reviewId,
        String filename,
        DocumentType documentType,
        ReviewStatus status,
        ReviewStep currentStep,
        @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss") LocalDateTime updatedAt) {

    static ReviewListItemResponse from(ReviewRepository.ListItem item) {
        return new ReviewListItemResponse(
                item.getReviewId(),
                item.getFilename(),
                DocumentType.PRODUCT_GUIDE,
                item.getStatus(),
                item.getCurrentStep(),
                item.getUpdatedAt());
    }
}
