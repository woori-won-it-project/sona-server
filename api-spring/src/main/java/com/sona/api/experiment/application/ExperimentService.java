package com.sona.api.experiment.application;

import com.sona.api.document.domain.Document;
import com.sona.api.document.domain.DocumentRepository;
import com.sona.api.document.domain.DocumentType;
import com.sona.api.experiment.api.ExperimentStatusResponse;
import com.sona.api.experiment.api.ExperimentSummaryResponse;
import com.sona.api.experiment.api.PersonaResponsesResponse;
import com.sona.api.experiment.api.PersonaResponsesResponse.Evidence;
import com.sona.api.experiment.api.PersonaResponsesResponse.Item;
import com.sona.api.experiment.api.StartExperimentRequest;
import com.sona.api.experiment.api.StartExperimentResponse;
import com.sona.api.experiment.domain.Experiment;
import com.sona.api.experiment.domain.ExperimentDocument;
import com.sona.api.experiment.domain.ExperimentDocumentRepository;
import com.sona.api.experiment.domain.ExperimentRepository;
import com.sona.api.experiment.domain.ExperimentResponse;
import com.sona.api.experiment.domain.ExperimentResponseRepository;
import com.sona.api.experiment.domain.ExperimentStatus;
import com.sona.api.experiment.domain.ExperimentType;
import com.sona.api.experiment.domain.ReadingMemo;
import com.sona.api.experiment.domain.ReadingMemoRepository;
import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import com.sona.api.persona.domain.ReviewPersona;
import com.sona.api.persona.domain.ReviewPersonaRepository;
import com.sona.api.question.application.QuestionApprovalChecker;
import com.sona.api.question.domain.Question;
import com.sona.api.question.domain.QuestionOption;
import com.sona.api.question.domain.QuestionOptionRepository;
import com.sona.api.review.application.ReviewFinder;
import com.sona.api.review.domain.Review;
import com.sona.api.review.domain.ReviewStep;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 실험 시작·조회 (기능 7, api.md 20~23). 실제 실행은 {@link ExperimentRunner} 가 백그라운드에서 한다. */
@Service
@RequiredArgsConstructor
public class ExperimentService {

    private final ExperimentRepository experimentRepository;
    private final ExperimentDocumentRepository experimentDocumentRepository;
    private final ExperimentResponseRepository experimentResponseRepository;
    private final ReadingMemoRepository readingMemoRepository;
    private final ReviewPersonaRepository reviewPersonaRepository;
    private final DocumentRepository documentRepository;
    private final QuestionOptionRepository questionOptionRepository;
    private final QuestionApprovalChecker questionApprovalChecker;
    private final ReviewFinder reviewFinder;
    private final ApplicationEventPublisher events;

    @Transactional
    public StartExperimentResponse start(Long memberId, Long reviewId, StartExperimentRequest request) {
        Review review = reviewFinder.getOwned(memberId, reviewId);
        boolean initial = request.parentExperimentId() == null;
        if (request.experimentType() != (initial ? ExperimentType.INITIAL : ExperimentType.RERUN)) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
        if (experimentRepository.existsByReviewIdAndStatus(reviewId, ExperimentStatus.RUNNING)) {
            throw new BusinessException(ErrorCode.REVIEW_PROCESSING);
        }
        List<Question> approved = questionApprovalChecker.requireApproved(reviewId);
        List<ReviewPersona> personas = reviewPersonaRepository.findByReviewId(reviewId);
        if (personas.isEmpty()) {
            throw new BusinessException(ErrorCode.PERSONA_NOT_SELECTED);
        }
        Document guide = documentRepository
                .findTopByReviewIdAndDocumentTypeOrderByVersionDesc(reviewId, DocumentType.PRODUCT_GUIDE)
                .orElseThrow(() -> new BusinessException(ErrorCode.REQUIRED_DOCUMENT_MISSING));

        Experiment parent = null;
        int round = 1;
        if (initial) {
            if (experimentRepository.existsByReviewIdAndParentExperimentIsNullAndStatusNot(
                    reviewId, ExperimentStatus.FAILED)) {
                throw new BusinessException(ErrorCode.INITIAL_EXPERIMENT_EXISTS);
            }
        } else {
            // 재실험: 바로 이전(가장 최근 완료) 실험을 기준으로, 새 버전 설명서가 있어야 한다
            parent = experimentRepository
                    .findTopByReviewIdAndStatusOrderByRoundNumberDesc(reviewId, ExperimentStatus.COMPLETED)
                    .filter(e -> e.getId().equals(request.parentExperimentId()))
                    .orElseThrow(() -> new BusinessException(ErrorCode.INVALID_PARENT_EXPERIMENT));
            if (guide.getVersion() <= guideVersion(parent.getId())) {
                throw new BusinessException(ErrorCode.NEW_DOCUMENT_REQUIRED);
            }
            round = parent.getRoundNumber() + 1;
        }

        Experiment experiment = experimentRepository.save(Experiment.builder()
                .review(review)
                .parentExperiment(parent)
                .roundNumber(round)
                .build());
        experimentDocumentRepository.save(ExperimentDocument.builder()
                .experiment(experiment)
                .document(guide)
                .build());
        // 약관은 페르소나가 읽지 않지만, 어떤 약관 기준의 실험인지 기록해 둔다
        documentRepository
                .findTopByReviewIdAndDocumentTypeOrderByVersionDesc(reviewId, DocumentType.TERMS)
                .ifPresent(terms -> experimentDocumentRepository.save(ExperimentDocument.builder()
                        .experiment(experiment)
                        .document(terms)
                        .build()));
        review.moveTo(ReviewStep.EXPERIMENT);
        events.publishEvent(new ExperimentStartedEvent(experiment.getId()));

        return new StartExperimentResponse(
                experiment.getId(),
                reviewId,
                initial ? ExperimentType.INITIAL : ExperimentType.RERUN,
                parent == null ? null : parent.getId(),
                round,
                guide.getVersion(),
                ExperimentStatus.RUNNING,
                personas.size() * approved.size());
    }

    @Transactional(readOnly = true)
    public ExperimentStatusResponse status(Long memberId, Long experimentId) {
        Experiment e = getOwned(memberId, experimentId);
        return new ExperimentStatusResponse(
                e.getId(), e.getReview().getId(), type(e), e.getRoundNumber(), e.getStatus(), e.getCreatedAt());
    }

    @Transactional(readOnly = true)
    public List<PersonaResponsesResponse> responses(Long memberId, Long experimentId) {
        getOwned(memberId, experimentId);
        List<ExperimentResponse> responses = experimentResponseRepository.findByExperimentId(experimentId);
        List<Long> questionIds =
                responses.stream().map(r -> r.getQuestion().getId()).distinct().toList();
        Map<String, QuestionOption> options =
                questionOptionRepository.findByQuestionIdInOrderByQuestionIdAscOptionKeyAsc(questionIds).stream()
                        .collect(Collectors.toMap(
                                o -> o.getQuestion().getId() + ":" + o.getOptionKey(), Function.identity()));
        Map<Long, String> memos = readingMemoRepository.findByExperimentId(experimentId).stream()
                .collect(Collectors.toMap(m -> m.getReviewPersona().getId(), ReadingMemo::getMemo));

        Map<ReviewPersona, List<ExperimentResponse>> byPersona = responses.stream()
                .sorted(Comparator.comparing(
                                (ExperimentResponse r) -> r.getReviewPersona().getId())
                        .thenComparing(r -> r.getQuestion().getId()))
                .collect(Collectors.groupingBy(
                        ExperimentResponse::getReviewPersona, LinkedHashMap::new, Collectors.toList()));

        return byPersona.entrySet().stream()
                .map(entry -> {
                    ReviewPersona rp = entry.getKey();
                    List<Item> items = entry.getValue().stream()
                            .map(r -> toItem(r, options.get(r.getQuestion().getId() + ":" + r.getSelectedOption())))
                            .toList();
                    return new PersonaResponsesResponse(
                            rp.getId(),
                            rp.getPersona().getName(),
                            rp.getPersona().getFinancialLiteracy(),
                            memos.get(rp.getId()),
                            items);
                })
                .toList();
    }

    private static Item toItem(ExperimentResponse r, QuestionOption option) {
        return new Item(
                r.getQuestion().getId(),
                r.getSelectedAnswer(),
                r.getSelectedOption(),
                option == null ? null : option.getOptionText(),
                option == null ? null : option.isCritical(),
                r.getResponseReason(),
                r.getGradingResult(),
                new Evidence(r.getDocument().getId(), r.getEvidencePage(), r.getEvidenceText()));
    }

    @Transactional(readOnly = true)
    public List<ExperimentSummaryResponse> list(Long memberId, Long reviewId) {
        reviewFinder.getOwned(memberId, reviewId);
        List<Experiment> experiments =
                experimentRepository.findByReviewIdAndStatusOrderByRoundNumberAsc(reviewId, ExperimentStatus.COMPLETED);
        Map<Long, List<ExperimentResponse>> responses =
                experimentResponseRepository
                        .findByExperimentIdIn(
                                experiments.stream().map(Experiment::getId).toList())
                        .stream()
                        .collect(Collectors.groupingBy(r -> r.getExperiment().getId()));
        return experiments.stream()
                .map(e -> new ExperimentSummaryResponse(
                        e.getId(),
                        type(e),
                        e.getParentExperiment() == null
                                ? null
                                : e.getParentExperiment().getId(),
                        e.getRoundNumber(),
                        guideVersion(e.getId()),
                        misunderstandingRate(responses.getOrDefault(e.getId(), List.of())),
                        e.getCreatedAt()))
                .toList();
    }

    /** 오해율 = (오답 + 판단 불가) / 전체 x 100, 소수 둘째 자리 (spec 5.4) */
    static double misunderstandingRate(List<ExperimentResponse> responses) {
        if (responses.isEmpty()) {
            return 0.0;
        }
        long misunderstood =
                responses.stream().filter(ExperimentResponse::isMisunderstood).count();
        return Math.round(misunderstood * 10000.0 / responses.size()) / 100.0;
    }

    private Experiment getOwned(Long memberId, Long experimentId) {
        return experimentRepository
                .findById(experimentId)
                .filter(e -> e.getReview().getMember().getId().equals(memberId))
                .orElseThrow(() -> new BusinessException(ErrorCode.NOT_FOUND));
    }

    private Long guideVersion(Long experimentId) {
        return experimentDocumentRepository.findByExperimentId(experimentId).stream()
                .map(ExperimentDocument::getDocument)
                .filter(d -> d.getDocumentType() == DocumentType.PRODUCT_GUIDE)
                .map(Document::getVersion)
                .findFirst()
                .orElse(0L);
    }

    private static ExperimentType type(Experiment e) {
        return e.isInitial() ? ExperimentType.INITIAL : ExperimentType.RERUN;
    }
}
