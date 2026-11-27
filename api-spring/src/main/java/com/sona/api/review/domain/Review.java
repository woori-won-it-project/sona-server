package com.sona.api.review.domain;

import com.sona.api.global.entity.BaseTimeEntity;
import com.sona.api.member.domain.Member;
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
import java.time.LocalDateTime;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** 검수 작업 하나. 문서·질문·실험이 모두 이 아래에 달리고, 삭제하면 함께 지워진다 (하드 delete). */
@Getter
@Entity
@Table(name = "reviews")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Review extends BaseTimeEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "member_id", nullable = false)
    private Member member;

    /** 비어 있으면 첫 상품설명서 파일명으로 채운다 */
    @Column(length = 255)
    private String title;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    private ReviewStatus status = ReviewStatus.IN_PROGRESS;

    @Enumerated(EnumType.STRING)
    @Column(name = "current_step", nullable = false, length = 30)
    private ReviewStep currentStep = ReviewStep.DOC_UPLOAD;

    @Column(name = "completed_at")
    private LocalDateTime completedAt;

    @Builder
    private Review(Member member, String title) {
        this.member = member;
        this.title = title;
    }

    public void changeTitle(String title) {
        this.title = title;
    }

    public void moveTo(ReviewStep step) {
        this.currentStep = step;
    }

    /** 검수 완료 처리. 이미 완료면 그대로 둔다. */
    public void complete() {
        if (this.status == ReviewStatus.COMPLETED) {
            return;
        }
        this.status = ReviewStatus.COMPLETED;
        this.completedAt = LocalDateTime.now();
    }

    /** 분석이 처리 중인지 (중복 실행 방지용). 실험 처리 중 여부는 experiments.status 로 본다. */
    public boolean isAnalyzing() {
        return currentStep == ReviewStep.ANALYZING;
    }
}
