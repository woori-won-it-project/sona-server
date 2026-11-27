package com.sona.api.document.domain;

import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface DocumentRepository extends JpaRepository<Document, Long> {

    List<Document> findByReviewIdOrderByDocumentTypeAscVersionAsc(Long reviewId);

    /** 이 종류의 최신 버전 (상품설명서면 가장 최근에 올린 판) */
    Optional<Document> findTopByReviewIdAndDocumentTypeOrderByVersionDesc(Long reviewId, DocumentType documentType);
}
