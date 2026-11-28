package com.sona.api.experiment.application;

import com.sona.api.document.domain.Clause;
import com.sona.api.document.domain.ClauseRepository;
import com.sona.api.document.domain.Document;
import com.sona.api.document.domain.DocumentType;
import com.sona.api.experiment.application.RunPlan.PersonaSlot;
import com.sona.api.experiment.application.RunPlan.QuestionSnapshot;
import com.sona.api.experiment.domain.Experiment;
import com.sona.api.experiment.domain.ExperimentDocument;
import com.sona.api.experiment.domain.ExperimentDocumentRepository;
import com.sona.api.experiment.domain.ExperimentRepository;
import com.sona.api.experiment.domain.ExperimentResponse;
import com.sona.api.experiment.domain.ExperimentResponseRepository;
import com.sona.api.experiment.domain.GradingResult;
import com.sona.api.experiment.domain.ReadingMemo;
import com.sona.api.experiment.domain.ReadingMemoRepository;
import com.sona.api.persona.ai.PersonaAi.GeneratedOptions;
import com.sona.api.persona.application.PersonaCard;
import com.sona.api.persona.domain.Persona;
import com.sona.api.persona.domain.ReviewPersona;
import com.sona.api.persona.domain.ReviewPersonaRepository;
import com.sona.api.persona.engine.PersonaProfile;
import com.sona.api.question.application.QuestionApprovalChecker;
import com.sona.api.question.domain.Question;
import com.sona.api.question.domain.QuestionOption;
import com.sona.api.question.domain.QuestionOptionRepository;
import com.sona.api.question.domain.QuestionRepository;
import com.sona.api.review.domain.ReviewStep;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/** 실험 실행 중 DB 를 읽고 쓰는 단계들. 단계마다 짧은 트랜잭션으로 끊는다 (AI 호출 동안 트랜잭션을 잡지 않으려고). */
@Component
@RequiredArgsConstructor
public class ExperimentSteps {

    private static final List<String> KEYS = List.of("A", "B", "C");

    private final ExperimentRepository experimentRepository;
    private final ExperimentDocumentRepository experimentDocumentRepository;
    private final ExperimentResponseRepository experimentResponseRepository;
    private final ReadingMemoRepository readingMemoRepository;
    private final ReviewPersonaRepository reviewPersonaRepository;
    private final QuestionRepository questionRepository;
    private final QuestionOptionRepository questionOptionRepository;
    private final QuestionApprovalChecker questionApprovalChecker;
    private final ClauseRepository clauseRepository;

    public record GradedAnswer(long questionId, String option, String reason, GradingResult result) {}

    @Transactional(readOnly = true)
    public RunPlan prepare(long experimentId) {
        Experiment experiment = experimentRepository.findById(experimentId).orElseThrow();
        Long reviewId = experiment.getReview().getId();

        Document guide = guideOf(experimentId);
        String guideText = clauseRepository.findByDocumentIdOrderBySequenceAsc(guide.getId()).stream()
                .map(ExperimentSteps::clauseText)
                .collect(Collectors.joining("\n"));
        if (guideText.isBlank()) {
            throw new IllegalStateException("상품설명서 텍스트가 비어 있습니다 (조항 추출 전).");
        }

        List<PersonaSlot> personas = reviewPersonaRepository.findWithPersonaByReviewId(reviewId).stream()
                .map(ExperimentSteps::slot)
                .toList();
        List<QuestionSnapshot> questions = questionApprovalChecker.requireApproved(reviewId).stream()
                .map(q -> new QuestionSnapshot(
                        q.getId(),
                        q.getQuestionText(),
                        q.getReferenceAnswer() == null
                                ? ""
                                : q.getReferenceAnswer().name(),
                        q.getReferenceAnswerReason()))
                .toList();
        return new RunPlan(experimentId, experiment.isInitial(), guide.getId(), guideText, personas, questions);
    }

    private Document guideOf(long experimentId) {
        return experimentDocumentRepository.findByExperimentId(experimentId).stream()
                .map(ExperimentDocument::getDocument)
                .filter(d -> d.getDocumentType() == DocumentType.PRODUCT_GUIDE)
                .findFirst()
                .orElseThrow(() -> new IllegalStateException("실험에 상품설명서가 없습니다."));
    }

    private static String clauseText(Clause c) {
        return c.getTitle() == null ? c.getContent() : "[" + c.getTitle() + "]\n" + c.getContent();
    }

    private static PersonaSlot slot(ReviewPersona rp) {
        Persona p = rp.getPersona();
        PersonaProfile profile = new PersonaProfile(
                p.getId(), p.getFinancialLiteracy(), p.getDiligence().doubleValue(), p.getDisposition());
        return new PersonaSlot(rp.getId(), profile, p.getInfoPath(), PersonaCard.of(p), PersonaCard.forReading(p));
    }

    /** 보기가 없는 질문 id */
    @Transactional(readOnly = true)
    public List<Long> questionsWithoutOptions(Collection<Long> questionIds) {
        Set<Long> having =
                questionOptionRepository.findByQuestionIdInOrderByQuestionIdAscOptionKeyAsc(questionIds).stream()
                        .map(o -> o.getQuestion().getId())
                        .collect(Collectors.toSet());
        return questionIds.stream().filter(id -> !having.contains(id)).toList();
    }

    /** AI 가 만든 보기를 저장한다. 정답 위치는 질문 id 로 섞어 고정한다 (같은 질문은 언제나 같은 순서) */
    @Transactional
    public void saveOptions(List<GeneratedOptions> generated, String guideText) {
        String compactGuide = guideText.replace(" ", "");
        for (GeneratedOptions g : generated) {
            if (g.wrong() == null || g.wrong().size() < 2 || g.correct() == null) {
                throw new IllegalStateException("보기를 3개 만들지 못했습니다. questionId=" + g.questionId());
            }
            Question question = questionRepository.findById(g.questionId()).orElseThrow();
            List<Grader.Option> opts = new ArrayList<>();
            opts.add(new Grader.Option(null, g.correct(), true, false));
            g.wrong().stream().limit(2).forEach(w -> opts.add(new Grader.Option(null, w.text(), false, w.critical())));
            Collections.shuffle(opts, new Random(g.questionId()));
            for (int i = 0; i < opts.size(); i++) {
                Grader.Option o = opts.get(i);
                questionOptionRepository.save(QuestionOption.builder()
                        .question(question)
                        .optionKey(KEYS.get(i))
                        .optionText(o.text())
                        .correct(o.correct())
                        .critical(o.critical())
                        .build());
            }
            // 설명서에 글자 그대로 있는 문구만 남긴다 (띄어쓰기 무시)
            List<String> phrases = g.keyPhrases() == null
                    ? List.of()
                    : g.keyPhrases().stream()
                            .filter(k -> k != null && !k.isBlank() && compactGuide.contains(k.replace(" ", "")))
                            .toList();
            question.assignKeyPhrases(String.join("\n", phrases));
        }
    }

    /** 질문 id → 보기 (A, B, C 순) */
    @Transactional(readOnly = true)
    public Map<Long, List<Grader.Option>> loadOptions(Collection<Long> questionIds) {
        Map<Long, List<Grader.Option>> out = new LinkedHashMap<>();
        for (QuestionOption o :
                questionOptionRepository.findByQuestionIdInOrderByQuestionIdAscOptionKeyAsc(questionIds)) {
            out.computeIfAbsent(o.getQuestion().getId(), k -> new ArrayList<>())
                    .add(new Grader.Option(o.getOptionKey(), o.getOptionText(), o.isCorrect(), o.isCritical()));
        }
        return out;
    }

    /** 질문 id → 핵심 문구 (보기를 만든 뒤 다시 읽는다) */
    @Transactional(readOnly = true)
    public Map<Long, List<String>> loadKeyPhrases(Collection<Long> questionIds) {
        Map<Long, List<String>> out = new LinkedHashMap<>();
        for (Question q : questionRepository.findAllById(questionIds)) {
            String k = q.getKeyPhrases();
            out.put(q.getId(), k == null || k.isBlank() ? List.of() : List.of(k.split("\n")));
        }
        return out;
    }

    @Transactional
    public void saveResult(
            long experimentId, long reviewPersonaId, String memo, String firstImpression, List<GradedAnswer> answers) {
        Experiment experiment = experimentRepository.getReferenceById(experimentId);
        ReviewPersona reviewPersona = reviewPersonaRepository.getReferenceById(reviewPersonaId);
        Document guide = guideOf(experimentId);
        readingMemoRepository.save(ReadingMemo.builder()
                .experiment(experiment)
                .reviewPersona(reviewPersona)
                .memo(memo)
                .firstImpression(firstImpression)
                .build());
        for (GradedAnswer a : answers) {
            experimentResponseRepository.save(ExperimentResponse.builder()
                    .experiment(experiment)
                    .reviewPersona(reviewPersona)
                    .document(guide)
                    .question(questionRepository.getReferenceById(a.questionId()))
                    .selectedOption(a.option())
                    .responseReason(a.reason())
                    .gradingResult(a.result())
                    .build());
        }
    }

    @Transactional
    public void complete(long experimentId) {
        Experiment experiment = experimentRepository.findById(experimentId).orElseThrow();
        experiment.complete();
        experiment.getReview().moveTo(ReviewStep.REPORT);
    }

    /** 실패: 그 실험의 응답·메모를 지우고, 검수 단계를 실험 전으로 되돌린다 (api.md 20) */
    @Transactional
    public void fail(long experimentId) {
        Experiment experiment = experimentRepository.findById(experimentId).orElseThrow();
        experimentResponseRepository.deleteByExperimentId(experimentId);
        readingMemoRepository.deleteByExperimentId(experimentId);
        experiment.fail();
        experiment.getReview().moveTo(experiment.isInitial() ? ReviewStep.PERSONA_SELECT : ReviewStep.REUPLOAD);
    }
}
