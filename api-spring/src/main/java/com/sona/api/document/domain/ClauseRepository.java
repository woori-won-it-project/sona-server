package com.sona.api.document.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ClauseRepository extends JpaRepository<Clause, Long> {

    List<Clause> findByDocumentIdOrderBySequenceAsc(Long documentId);
}
