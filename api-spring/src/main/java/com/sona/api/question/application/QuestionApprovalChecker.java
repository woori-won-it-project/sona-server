package com.sona.api.question.application;

import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import com.sona.api.question.domain.Question;
import com.sona.api.question.domain.QuestionRepository;
import com.sona.api.question.domain.QuestionStatus;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/** 페르소나 선택·실험 시작 전 확인: 선택한 질문이 모두 승인됐고 승인 질문이 1개 이상인지 (api.md 19, 20) */
@Component
@RequiredArgsConstructor
public class QuestionApprovalChecker {

    private final QuestionRepository questionRepository;

    /** @return 승인된 질문 (id 순) */
    public List<Question> requireApproved(Long reviewId) {
        List<Question> notApproved =
                questionRepository.findByReviewIdAndStatusOrderByIdAsc(reviewId, QuestionStatus.SELECTED);
        if (!notApproved.isEmpty()) {
            throw new BusinessException(
                    ErrorCode.QUESTION_NOT_APPROVED,
                    Map.of(
                            "questionIds",
                            notApproved.stream().map(Question::getId).toList()));
        }
        List<Question> approved =
                questionRepository.findByReviewIdAndStatusOrderByIdAsc(reviewId, QuestionStatus.APPROVED);
        if (approved.isEmpty()) {
            throw new BusinessException(ErrorCode.QUESTION_NOT_APPROVED, Map.of("questionIds", List.of()));
        }
        return approved;
    }
}
