package com.sona.api.question.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface QuestionEvidenceRepository extends JpaRepository<QuestionEvidence, Long> {

    List<QuestionEvidence> findByQuestionIdIn(List<Long> questionIds);
}
