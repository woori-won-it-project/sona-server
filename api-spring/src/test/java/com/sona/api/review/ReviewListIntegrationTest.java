package com.sona.api.review;

import static org.hamcrest.Matchers.nullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.sona.api.global.auth.TokenProvider;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.transaction.annotation.Transactional;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Transactional
class ReviewListIntegrationTest {

    @Autowired
    MockMvc mockMvc;

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    TokenProvider tokenProvider;

    Long memberId;

    @BeforeEach
    void createMember() {
        memberId = insertMember("review-list-member");
    }

    @Test
    void returnsOnlyOwnedReviewsOrderedByUpdatedAtAndIdWithLatestGuide() throws Exception {
        Long older = insertReview(memberId, "COMPLETED", "2026-11-25 12:00:00");
        Long firstTied = insertReview(memberId, "IN_PROGRESS", "2026-11-28 10:30:00.123");
        Long secondTied = insertReview(memberId, "IN_PROGRESS", "2026-11-28 10:30:00.123");
        insertReview(insertMember("review-list-other"), "IN_PROGRESS", "2026-11-29 12:00:00");
        insertDocument(secondTied, "PRODUCT_GUIDE", 2, "latest.pdf");
        insertDocument(secondTied, "PRODUCT_GUIDE", 1, "older.pdf");
        insertDocument(secondTied, "TERMS", 3, "terms.pdf");
        insertDocument(firstTied, "TERMS", 1, "terms-only.pdf");

        mockMvc.perform(authenticatedList())
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.length()").value(3))
                .andExpect(jsonPath("$.data[0].reviewId").value(secondTied))
                .andExpect(jsonPath("$.data[0].filename").value("latest.pdf"))
                .andExpect(jsonPath("$.data[0].documentType").value("PRODUCT_GUIDE"))
                .andExpect(jsonPath("$.data[0].status").value("IN_PROGRESS"))
                .andExpect(jsonPath("$.data[0].currentStep").value("DOC_UPLOAD"))
                .andExpect(jsonPath("$.data[0].updatedAt").value("2026-11-28T10:30:00"))
                .andExpect(jsonPath("$.data[0].s3Path").doesNotHaveJsonPath())
                .andExpect(jsonPath("$.data[0].fileSize").doesNotHaveJsonPath())
                .andExpect(jsonPath("$.data[1].reviewId").value(firstTied))
                .andExpect(jsonPath("$.data[1].filename").value(nullValue()))
                .andExpect(jsonPath("$.data[1].documentType").value("PRODUCT_GUIDE"))
                .andExpect(jsonPath("$.data[2].reviewId").value(older));
    }

    @Test
    void filtersBeforeApplyingLimitAndKeepsTimestampOrderAheadOfIdOrder() throws Exception {
        Long recentCompleted = insertReview(memberId, "COMPLETED", "2026-11-27 12:00:00");
        Long oldCompleted = insertReview(memberId, "COMPLETED", "2026-11-26 12:00:00");
        Long inProgress = insertReview(memberId, "IN_PROGRESS", "2026-11-28 12:00:00");

        mockMvc.perform(authenticatedList().param("status", "COMPLETED").param("limit", "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.length()").value(1))
                .andExpect(jsonPath("$.data[0].reviewId").value(recentCompleted));

        mockMvc.perform(authenticatedList().param("status", "COMPLETED").param("limit", "2147483647"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.length()").value(2))
                .andExpect(jsonPath("$.data[1].reviewId").value(oldCompleted));

        mockMvc.perform(authenticatedList().param("status", "IN_PROGRESS"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.length()").value(1))
                .andExpect(jsonPath("$.data[0].reviewId").value(inProgress));
    }

    @Test
    void returnsAnEmptyListWhenNoReviewsMatch() throws Exception {
        insertReview(memberId, "IN_PROGRESS", "2026-11-28 12:00:00");
        mockMvc.perform(authenticatedList().param("status", "COMPLETED"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").isEmpty());
    }

    @ParameterizedTest
    @CsvSource({
        "status, UNKNOWN",
        "status, completed",
        "status, ''",
        "limit, 0",
        "limit, -1",
        "limit, 1.5",
        "limit, 2147483648",
        "limit, ''"
    })
    void rejectsInvalidFilters(String parameter, String value) throws Exception {
        mockMvc.perform(authenticatedList().param(parameter, value))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
    }

    @Test
    void rejectsUnauthenticatedRequestsAndLeavesDetailUnmapped() throws Exception {
        mockMvc.perform(get("/api/v1/reviews"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHORIZED"));
        Long reviewId = insertReview(memberId, "IN_PROGRESS", "2026-11-28 12:00:00");
        mockMvc.perform(get("/api/v1/reviews/{reviewId}", reviewId)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + tokenProvider.issue(memberId)))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("NOT_FOUND"));
    }

    private MockHttpServletRequestBuilder authenticatedList() {
        return get("/api/v1/reviews").header(HttpHeaders.AUTHORIZATION, "Bearer " + tokenProvider.issue(memberId));
    }

    private Long insertMember(String employeeNumber) {
        return jdbc.queryForObject(
                "insert into members (employee_number, name, password_hash) values (?, 'test', 'unused') returning id",
                Long.class,
                employeeNumber);
    }

    private Long insertReview(Long owner, String reviewStatus, String updatedAt) {
        return jdbc.queryForObject(
                "insert into reviews (member_id, status, updated_at) values (?, ?, cast(? as timestamp)) returning id",
                Long.class,
                owner,
                reviewStatus,
                updatedAt);
    }

    private void insertDocument(Long reviewId, String type, long version, String filename) {
        jdbc.update(
                "insert into documents (review_id, document_type, version, original_filename, s3_path) values (?, ?, ?, ?, ?)",
                reviewId,
                type,
                version,
                filename,
                "test/" + filename);
    }
}
