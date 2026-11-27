package com.sona.api.experiment.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ReadingMemoRepository extends JpaRepository<ReadingMemo, Long> {

    List<ReadingMemo> findByExperimentId(Long experimentId);

    void deleteByExperimentId(Long experimentId);
}
