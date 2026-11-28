package com.sona.api.review.application;

import com.sona.api.document.domain.DocumentRepository;
import com.sona.api.document.domain.DocumentType;
import com.sona.api.review.domain.Review;
import com.sona.api.review.domain.ReviewRepository;
import com.sona.api.review.domain.ReviewStatus;
import java.util.EnumSet;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Limit;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class ReviewQueryService {

    private final ReviewRepository reviewRepository;
    private final ReviewFinder reviewFinder;
    private final DocumentRepository documentRepository;

    @Transactional(readOnly = true)
    public List<ReviewRepository.ListItem> list(Long memberId, ReviewStatus status, Limit limit) {
        EnumSet<ReviewStatus> statuses = status == null ? EnumSet.allOf(ReviewStatus.class) : EnumSet.of(status);
        return reviewRepository.findListItems(memberId, statuses, DocumentType.PRODUCT_GUIDE, limit);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public ReviewDetailSnapshot getDetailSnapshot(Long memberId, Long reviewId) {
        Review review = reviewFinder.getOwned(memberId, reviewId);
        List<ReviewDetailSnapshot.DocumentMetadata> documents =
                documentRepository.findByReviewIdOrderByDocumentTypeAscVersionAsc(reviewId).stream()
                        .map(ReviewDetailSnapshot.DocumentMetadata::from)
                        .toList();
        return new ReviewDetailSnapshot(
                review.getId(),
                review.getTitle(),
                review.getStatus(),
                review.getCurrentStep(),
                documents,
                review.getCreatedAt(),
                review.getUpdatedAt(),
                review.getCompletedAt());
    }
}
