package com.sona.api.experiment.application;

import com.sona.api.persona.domain.InfoPath;
import com.sona.api.persona.engine.PersonaProfile;
import java.util.List;

/** 백그라운드 실행에 필요한 값만 미리 꺼내 둔 것 (스레드 사이에 JPA 엔티티를 넘기지 않으려고). */
public record RunPlan(
        long experimentId,
        boolean initial,
        long guideDocumentId,
        String guideText,
        List<PersonaSlot> personas,
        List<QuestionSnapshot> questions) {

    /** card: 답할 때 소개 글, readingCard: 읽고 메모할 때 소개 글 (메모 습관 포함) */
    public record PersonaSlot(
            long reviewPersonaId, PersonaProfile profile, InfoPath infoPath, String card, String readingCard) {}

    public record QuestionSnapshot(
            long questionId, String questionText, String referenceAnswer, String referenceReason) {}

    public boolean needsAgentTalk() {
        return personas.stream().anyMatch(p -> p.infoPath() == InfoPath.AGENT_TALK);
    }
}
