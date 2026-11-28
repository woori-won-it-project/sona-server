package com.sona.api.review.domain;

import com.sona.api.document.domain.DocumentType;
import java.time.LocalDateTime;
import java.util.Collection;
import java.util.List;
import org.springframework.data.domain.Limit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ReviewRepository extends JpaRepository<Review, Long> {

    @Query("""
            select r.id as reviewId, guide.originalFilename as filename, r.status as status,
                   r.currentStep as currentStep, r.updatedAt as updatedAt
            from Review r
            left join Document guide on guide.review = r and guide.documentType = :documentType
            where r.member.id = :memberId and r.status in :statuses
              and (guide.id is null or guide.version = (
                  select max(d.version) from Document d
                  where d.review = r and d.documentType = :documentType
              ))
            order by r.updatedAt desc, r.id desc
            """)
    List<ListItem> findListItems(
            @Param("memberId") Long memberId,
            @Param("statuses") Collection<ReviewStatus> statuses,
            @Param("documentType") DocumentType documentType,
            Limit limit);

    interface ListItem {
        Long getReviewId();

        String getFilename();

        ReviewStatus getStatus();

        ReviewStep getCurrentStep();

        LocalDateTime getUpdatedAt();
    }
}
