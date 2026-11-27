package com.sona.api.question.domain;

import com.sona.api.global.entity.BaseCreatedEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 3지선다 보기 하나 (spec 4.7.2). 질문마다 정답 1개 + 오해 보기 2개.
 * 첫 실험 때 한 번 만들어 저장하고, 재실험에도 같은 보기를 쓴다 (버전 비교를 공정하게).
 */
@Getter
@Entity
@Table(name = "question_options", uniqueConstraints = @UniqueConstraint(columnNames = {"question_id", "option_key"}))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class QuestionOption extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "question_id", nullable = false)
    private Question question;

    /** A / B / C */
    @Column(name = "option_key", nullable = false, length = 1)
    private String optionKey;

    @Column(name = "option_text", nullable = false, columnDefinition = "TEXT")
    private String optionText;

    @Column(name = "is_correct", nullable = false)
    private boolean correct;

    /** 실제보다 더 받는다고 믿는 오해 (치명적 오해) */
    @Column(name = "is_critical", nullable = false)
    private boolean critical;

    @Builder
    private QuestionOption(Question question, String optionKey, String optionText, boolean correct, boolean critical) {
        this.question = question;
        this.optionKey = optionKey;
        this.optionText = optionText;
        this.correct = correct;
        this.critical = critical;
    }
}
