package com.sona.api.question.domain;

import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface QuestionOptionRepository extends JpaRepository<QuestionOption, Long> {

    List<QuestionOption> findByQuestionIdInOrderByQuestionIdAscOptionKeyAsc(Collection<Long> questionIds);
}
