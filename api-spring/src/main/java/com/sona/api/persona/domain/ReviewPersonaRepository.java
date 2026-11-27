package com.sona.api.persona.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ReviewPersonaRepository extends JpaRepository<ReviewPersona, Long> {

    List<ReviewPersona> findByReviewId(Long reviewId);
}
