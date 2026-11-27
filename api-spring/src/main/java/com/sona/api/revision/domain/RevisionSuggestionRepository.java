package com.sona.api.revision.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface RevisionSuggestionRepository extends JpaRepository<RevisionSuggestion, Long> {

    List<RevisionSuggestion> findByExperimentId(Long experimentId);

    boolean existsByExperimentIdAndQuestionId(Long experimentId, Long questionId);
}
