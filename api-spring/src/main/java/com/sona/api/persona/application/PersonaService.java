package com.sona.api.persona.application;

import com.sona.api.experiment.domain.ExperimentRepository;
import com.sona.api.experiment.domain.ExperimentStatus;
import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import com.sona.api.persona.api.PersonaResponse;
import com.sona.api.persona.api.SelectPersonasResponse;
import com.sona.api.persona.api.SelectPersonasResponse.SelectedPersona;
import com.sona.api.persona.domain.Persona;
import com.sona.api.persona.domain.PersonaRepository;
import com.sona.api.persona.domain.ReviewPersona;
import com.sona.api.persona.domain.ReviewPersonaRepository;
import com.sona.api.question.application.QuestionApprovalChecker;
import com.sona.api.review.application.ReviewFinder;
import com.sona.api.review.domain.Review;
import com.sona.api.review.domain.ReviewStep;
import java.util.Comparator;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 페르소나 목록·선택 (기능 7, api.md 18·19) */
@Service
@RequiredArgsConstructor
public class PersonaService {

    private final PersonaRepository personaRepository;
    private final ReviewPersonaRepository reviewPersonaRepository;
    private final ExperimentRepository experimentRepository;
    private final ReviewFinder reviewFinder;
    private final QuestionApprovalChecker questionApprovalChecker;

    @Transactional(readOnly = true)
    public List<PersonaResponse> list() {
        return personaRepository.findAll(Sort.by("id")).stream()
                .map(PersonaResponse::from)
                .toList();
    }

    /** 보낸 목록 전체로 덮어쓴다. 첫 실험 뒤에는 바꿀 수 없다 (spec 5.3) */
    @Transactional
    public SelectPersonasResponse select(Long memberId, Long reviewId, List<Long> personaIds) {
        reviewFinder.getOwned(memberId, reviewId);
        if (experimentRepository.existsByReviewIdAndStatusNot(reviewId, ExperimentStatus.FAILED)) {
            throw new BusinessException(ErrorCode.REVIEW_LOCKED);
        }
        questionApprovalChecker.requireApproved(reviewId);

        List<Long> ids = personaIds.stream().distinct().toList();
        List<Persona> personas = personaRepository.findAllById(ids);
        if (personas.size() != ids.size()) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }

        // 일괄 삭제 쿼리가 영속성 컨텍스트를 비우므로 검수는 그 뒤에 다시 읽는다
        reviewPersonaRepository.deleteByReviewIdInBulk(reviewId);
        Review review = reviewFinder.getOwned(memberId, reviewId);
        List<SelectedPersona> selected = personas.stream()
                .sorted(Comparator.comparing(Persona::getId))
                .map(p -> reviewPersonaRepository.save(
                        ReviewPersona.builder().review(review).persona(p).build()))
                .map(rp -> new SelectedPersona(
                        rp.getId(), rp.getPersona().getId(), rp.getPersona().getName()))
                .toList();
        review.moveTo(ReviewStep.PERSONA_SELECT);
        return new SelectPersonasResponse(reviewId, selected, selected.size());
    }
}
