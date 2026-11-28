package com.sona.api.experiment.application;

import com.sona.api.experiment.application.ExperimentSteps.GradedAnswer;
import com.sona.api.experiment.application.RunPlan.PersonaSlot;
import com.sona.api.experiment.application.RunPlan.QuestionSnapshot;
import com.sona.api.persona.ai.PersonaAi;
import com.sona.api.persona.ai.PersonaAi.GeneratedOptions;
import com.sona.api.persona.ai.PersonaAi.Memo;
import com.sona.api.persona.ai.PersonaAi.OptionView;
import com.sona.api.persona.ai.PersonaAi.PersonaAnswer;
import com.sona.api.persona.ai.PersonaAi.QuestionBrief;
import com.sona.api.persona.ai.PersonaAi.QuestionWithOptions;
import com.sona.api.persona.domain.InfoPath;
import com.sona.api.persona.engine.ContentUnit;
import com.sona.api.persona.engine.PersonaReader;
import com.sona.api.persona.engine.ReadResult;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.function.Function;
import java.util.stream.Collectors;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

/**
 * 실험 백그라운드 실행 (spec 4.7.2).
 * 1) 질문마다 3지선다 보기 준비 (없으면 AI 가 한 번 만들고 저장)
 * 2) 페르소나마다: 정보 경로의 글을 규칙대로 덜어 내 읽기 → 메모 → 메모만 보고 보기 고르기 → 코드 채점 → 저장
 * 3) 모두 끝나면 COMPLETED, 하나라도 실패하면 FAILED (응답·메모 삭제)
 *
 * TODO: spec 8장 원칙대로 RabbitMQ 큐로 옮긴다. 지금은 같은 앱 안의 스레드 풀로 실행한다.
 */
@Slf4j
@Component
public class ExperimentRunner {

    private final ExperimentSteps steps;
    private final PersonaAi ai;
    private final Executor personaExecutor;

    public ExperimentRunner(
            ExperimentSteps steps, PersonaAi ai, @Qualifier("personaExecutor") Executor personaExecutor) {
        this.steps = steps;
        this.ai = ai;
        this.personaExecutor = personaExecutor;
    }

    @Async("experimentExecutor")
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onStarted(ExperimentStartedEvent event) {
        run(event.experimentId());
    }

    public void run(long experimentId) {
        try {
            RunPlan plan = steps.prepare(experimentId);
            List<Long> questionIds =
                    plan.questions().stream().map(QuestionSnapshot::questionId).toList();
            prepareOptions(plan, questionIds);
            Map<Long, List<Grader.Option>> options = steps.loadOptions(questionIds);
            Map<Long, List<String>> keyPhrases = steps.loadKeyPhrases(questionIds);

            List<QuestionWithOptions> views = plan.questions().stream()
                    .map(q -> new QuestionWithOptions(
                            q.questionId(),
                            q.questionText(),
                            options.get(q.questionId()).stream()
                                    .map(o -> new OptionView(o.key(), o.text()))
                                    .toList()))
                    .toList();
            List<ContentUnit> units = plan.questions().stream()
                    .map(q -> new ContentUnit(
                            String.valueOf(q.questionId()), keyPhrases.getOrDefault(q.questionId(), List.of())))
                    .filter(u -> !u.phrases().isEmpty())
                    .toList();
            List<String> hardTerms = ai.extractHardTerms(plan.guideText());
            String agentTalk = plan.needsAgentTalk() ? ai.agentTalk(plan.guideText()) : null;

            List<CompletableFuture<Void>> jobs = plan.personas().stream()
                    .map(slot -> CompletableFuture.runAsync(
                            () -> runPersona(plan, slot, agentTalk, units, hardTerms, views, options), personaExecutor))
                    .toList();
            CompletableFuture.allOf(jobs.toArray(new CompletableFuture[0])).join();

            steps.complete(experimentId);
            log.info(
                    "실험 완료 experimentId={} personas={} questions={}",
                    experimentId,
                    plan.personas().size(),
                    questionIds.size());
        } catch (RuntimeException e) {
            log.error("실험 실패 experimentId={}", experimentId, e);
            steps.fail(experimentId);
        }
    }

    private void prepareOptions(RunPlan plan, List<Long> questionIds) {
        List<Long> missing = steps.questionsWithoutOptions(questionIds);
        if (missing.isEmpty()) {
            return;
        }
        List<QuestionBrief> briefs = plan.questions().stream()
                .filter(q -> missing.contains(q.questionId()))
                .map(q -> new QuestionBrief(q.questionId(), q.questionText(), q.referenceAnswer(), q.referenceReason()))
                .toList();
        Map<Long, GeneratedOptions> byId = ai.generateOptions(plan.guideText(), briefs).stream()
                .filter(g -> missing.contains(g.questionId()))
                .collect(Collectors.toMap(GeneratedOptions::questionId, Function.identity(), (a, b) -> a));
        if (byId.size() != missing.size()) {
            throw new IllegalStateException("보기를 만들지 못한 질문이 있습니다. 필요=" + missing + ", 받은=" + byId.keySet());
        }
        steps.saveOptions(new ArrayList<>(byId.values()), plan.guideText());
    }

    private void runPersona(
            RunPlan plan,
            PersonaSlot slot,
            String agentTalk,
            List<ContentUnit> units,
            List<String> hardTerms,
            List<QuestionWithOptions> views,
            Map<Long, List<Grader.Option>> options) {
        String text = slot.infoPath() == InfoPath.GUIDE ? plan.guideText() : agentTalk;
        ReadResult read = PersonaReader.read(slot.profile(), text, units, hardTerms);

        Memo memo = ai.writeMemo(slot.readingCard(), slot.infoPath().label(), read.seenText(), read.memoBudget());
        List<String> lines = PersonaReader.cutMemo(memo.lines() == null ? List.of() : memo.lines(), read.memoBudget());
        String memoText = lines.isEmpty()
                ? "(기억나는 내용이 없음)"
                : lines.stream().map(l -> "- " + l).collect(Collectors.joining("\n"));

        Map<Long, PersonaAnswer> answers = new HashMap<>();
        for (PersonaAnswer a : ai.answer(slot.card(), memoText, views)) {
            answers.putIfAbsent(a.questionId(), a);
        }
        List<GradedAnswer> graded = new ArrayList<>();
        for (QuestionWithOptions q : views) {
            PersonaAnswer a = answers.get(q.questionId());
            String choice = a == null ? null : a.choice();
            String reason = a == null ? "응답을 받지 못했습니다." : a.reason();
            graded.add(new GradedAnswer(
                    q.questionId(), choice, reason, Grader.grade(options.get(q.questionId()), choice)));
        }
        steps.saveResult(plan.experimentId(), slot.reviewPersonaId(), memoText, memo.firstImpression(), graded);
        log.info(
                "페르소나 완료 experimentId={} reviewPersonaId={} 읽은문장={}/{} 놓친내용={} 잘린문장={} 가린용어={}",
                plan.experimentId(),
                slot.reviewPersonaId(),
                read.readCount(),
                read.totalSentences(),
                read.missedUnits().size(),
                read.cutSentences(),
                read.maskedTerms().size());
    }
}
