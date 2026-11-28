package com.sona.api.review.api;

import com.sona.api.global.auth.LoginMember;
import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import com.sona.api.global.response.ApiResponse;
import com.sona.api.review.application.ReviewQueryService;
import com.sona.api.review.domain.ReviewStatus;
import io.swagger.v3.oas.annotations.Operation;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Limit;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/reviews")
@RequiredArgsConstructor
public class ReviewController {

    private final ReviewQueryService reviewQueryService;

    @Operation(summary = "본인 검수 목록 조회 (5)")
    @GetMapping
    public ApiResponse<List<ReviewListItemResponse>> list(
            @LoginMember Long memberId,
            @RequestParam(name = "status", required = false) String status,
            @RequestParam(name = "limit", required = false) String limit) {
        ReviewStatus statusFilter;
        int maxResults;
        try {
            statusFilter = status == null ? null : ReviewStatus.valueOf(status);
            maxResults = limit == null ? 0 : Integer.parseInt(limit);
        } catch (IllegalArgumentException e) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
        if (limit != null && maxResults <= 0) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }

        Limit resultLimit = limit == null ? Limit.unlimited() : Limit.of(maxResults);
        return ApiResponse.of(reviewQueryService.list(memberId, statusFilter, resultLimit).stream()
                .map(ReviewListItemResponse::from)
                .toList());
    }
}
