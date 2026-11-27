package com.sona.api.persona.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ReviewPersonaRepository extends JpaRepository<ReviewPersona, Long> {

    List<ReviewPersona> findByReviewId(Long reviewId);

    @Query("select rp from ReviewPersona rp join fetch rp.persona where rp.review.id = :reviewId order by rp.id")
    List<ReviewPersona> findWithPersonaByReviewId(@Param("reviewId") Long reviewId);

    @Modifying(flushAutomatically = true, clearAutomatically = true)
    @Query("delete from ReviewPersona rp where rp.review.id = :reviewId")
    void deleteByReviewIdInBulk(@Param("reviewId") Long reviewId);
}
