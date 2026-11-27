package com.sona.api.review.application;

import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import com.sona.api.review.domain.Review;
import com.sona.api.review.domain.ReviewRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/** 로그인 회원의 검수만 꺼낸다. 남의 검수는 있는지 숨기고 404 (api.md 0) */
@Component
@RequiredArgsConstructor
public class ReviewFinder {

    private final ReviewRepository reviewRepository;

    public Review getOwned(Long memberId, Long reviewId) {
        return reviewRepository
                .findById(reviewId)
                .filter(r -> r.getMember().getId().equals(memberId))
                .orElseThrow(() -> new BusinessException(ErrorCode.NOT_FOUND));
    }
}
