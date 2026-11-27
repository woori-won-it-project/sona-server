package com.sona.api.persona.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** 미리 정해 둔 페르소나 (예: 보장 요약형). 서비스에서는 읽기만 한다. */
@Getter
@Entity
@Table(name = "personas")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Persona {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 100)
    private String name;

    @Enumerated(EnumType.STRING)
    @Column(name = "financial_literacy", nullable = false, length = 20)
    private FinancialLiteracy financialLiteracy;

    @Column(name = "reading_behavior", nullable = false, columnDefinition = "TEXT")
    private String readingBehavior;

    @Column(columnDefinition = "TEXT")
    private String description;

    /** AI 에게 주는 성격 설명. API 응답에는 넣지 않는다. */
    @Column(nullable = false, columnDefinition = "TEXT")
    private String prompt;
}
