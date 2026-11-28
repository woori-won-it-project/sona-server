package com.sona.api.review;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sona.api.document.domain.DocumentType;
import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import com.sona.api.review.application.ReviewDetailSnapshot;
import com.sona.api.review.application.ReviewQueryService;
import com.sona.api.review.domain.ReviewStatus;
import com.sona.api.review.domain.ReviewStep;
import java.time.LocalDateTime;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

@SpringBootTest
@ActiveProfiles("test")
@Transactional
class ReviewDetailIntegrationTest {

    @Autowired
    ReviewQueryService reviewQueryService;

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    ObjectMapper objectMapper;

    Long memberId;
    Long reviewId;

    @BeforeEach
    void createReview() {
        memberId = jdbc.queryForObject(
                "insert into members (employee_number, name, password_hash) values ('review-detail-member', 'test', 'unused') returning id",
                Long.class);
        reviewId = jdbc.queryForObject("""
                insert into reviews (member_id, current_step, created_at, updated_at)
                values (?, 'ANSWER_APPROVE', timestamp '2026-11-25 10:00:00', timestamp '2026-11-28 10:30:00') returning id
                """, Long.class, memberId);
    }

    @Test
    void copiesReviewStateAndAllDocumentVersionsWithoutSerializingStoragePaths() {
        insertDocument("PRODUCT_GUIDE", 2, "guide-v2.pdf");
        Long firstGuide = insertDocument("PRODUCT_GUIDE", 1, "guide-v1.pdf");
        insertDocument("TERMS", 1, "terms.pdf");

        ReviewDetailSnapshot detail = reviewQueryService.getDetailSnapshot(memberId, reviewId);

        assertThat(detail.reviewId()).isEqualTo(reviewId);
        assertThat(detail.title()).isNull();
        assertThat(detail.status()).isEqualTo(ReviewStatus.IN_PROGRESS);
        assertThat(detail.currentStep()).isEqualTo(ReviewStep.ANSWER_APPROVE);
        assertThat(detail.createdAt()).isEqualTo(LocalDateTime.of(2026, 11, 25, 10, 0));
        assertThat(detail.updatedAt()).isEqualTo(LocalDateTime.of(2026, 11, 28, 10, 30));
        assertThat(detail.completedAt()).isNull();
        assertThat(detail.documents())
                .extracting(ReviewDetailSnapshot.DocumentMetadata::filename)
                .containsExactly("guide-v1.pdf", "guide-v2.pdf", "terms.pdf");
        assertThat(detail.documents().getFirst())
                .isEqualTo(new ReviewDetailSnapshot.DocumentMetadata(
                        firstGuide, DocumentType.PRODUCT_GUIDE, "guide-v1.pdf", 1L, "test/guide-v1.pdf"));
        JsonNode documentJson = objectMapper.valueToTree(detail.documents().getFirst());
        assertThat(documentJson.has("s3Path")).isFalse();
        assertThat(documentJson.has("fileSize")).isFalse();
    }

    @Test
    void returnsEmptyDocumentsAndTheStoredCompletionTimeForACompletedReview() {
        jdbc.update(
                "update reviews set status = 'COMPLETED', completed_at = timestamp '2026-11-28 11:00:00' where id = ?",
                reviewId);

        ReviewDetailSnapshot detail = reviewQueryService.getDetailSnapshot(memberId, reviewId);

        assertThat(detail.documents()).isEmpty();
        assertThat(detail.status()).isEqualTo(ReviewStatus.COMPLETED);
        assertThat(detail.completedAt()).isEqualTo(LocalDateTime.of(2026, 11, 28, 11, 0));
    }

    @Test
    void treatsMissingAndOtherMembersReviewsAsNotFound() {
        Long otherMember = jdbc.queryForObject(
                "insert into members (employee_number, name, password_hash) values ('review-detail-other', 'test', 'unused') returning id",
                Long.class);

        assertNotFound(otherMember, reviewId);
        assertNotFound(memberId, -1L);
    }

    private void assertNotFound(Long owner, Long id) {
        assertThatThrownBy(() -> reviewQueryService.getDetailSnapshot(owner, id))
                .isInstanceOfSatisfying(
                        BusinessException.class,
                        exception -> assertThat(exception.getErrorCode()).isEqualTo(ErrorCode.NOT_FOUND));
    }

    private Long insertDocument(String type, long version, String filename) {
        return jdbc.queryForObject(
                "insert into documents (review_id, document_type, version, original_filename, s3_path) values (?, ?, ?, ?, ?) returning id",
                Long.class,
                reviewId,
                type,
                version,
                filename,
                "test/" + filename);
    }
}
