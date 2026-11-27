package com.sona.api.experiment.domain;

import com.sona.api.document.domain.Document;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** 이 실험에 어떤 문서(버전)를 썼는지. V1 과 V2 를 구분하는 기준. */
@Getter
@Entity
@Table(name = "experiment_documents")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ExperimentDocument {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "experiment_id", nullable = false)
    private Experiment experiment;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "document_id", nullable = false)
    private Document document;

    @Builder
    private ExperimentDocument(Experiment experiment, Document document) {
        this.experiment = experiment;
        this.document = document;
    }
}
