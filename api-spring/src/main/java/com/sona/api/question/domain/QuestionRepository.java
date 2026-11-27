package com.sona.api.question.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface QuestionRepository extends JpaRepository<Question, Long> {

    List<Question> findByReviewIdOrderByIdAsc(Long reviewId);

    List<Question> findByReviewIdAndStatusOrderByIdAsc(Long reviewId, QuestionStatus status);
}
