package com.sona.api.experiment.api;

import com.sona.api.experiment.application.ExperimentService;
import com.sona.api.global.auth.LoginMember;
import com.sona.api.global.response.ApiResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "7. 페르소나 · 실험", description = "페르소나 목록·선택, 실험 시작·조회")
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class ExperimentController {

    private final ExperimentService experimentService;

    @Operation(summary = "실험 시작 · 재실험 (20, 28)", description = "202 로 바로 응답하고 백그라운드에서 실행한다. 끝났는지는 21번으로 확인")
    @PostMapping("/reviews/{reviewId}/experiments")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ApiResponse<StartExperimentResponse> start(
            @LoginMember Long memberId,
            @PathVariable Long reviewId,
            @Valid @RequestBody StartExperimentRequest request) {
        return ApiResponse.of(experimentService.start(memberId, reviewId, request));
    }

    @Operation(summary = "실험 상태 (21)")
    @GetMapping("/experiments/{experimentId}")
    public ApiResponse<ExperimentStatusResponse> status(@LoginMember Long memberId, @PathVariable Long experimentId) {
        return ApiResponse.of(experimentService.status(memberId, experimentId));
    }

    @Operation(summary = "전체 페르소나 응답 (22)")
    @GetMapping("/experiments/{experimentId}/responses")
    public ApiResponse<List<PersonaResponsesResponse>> responses(
            @LoginMember Long memberId, @PathVariable Long experimentId) {
        return ApiResponse.of(experimentService.responses(memberId, experimentId));
    }

    @Operation(summary = "실험 목록 (23)", description = "COMPLETED 실험만, roundNumber 오름차순")
    @GetMapping("/reviews/{reviewId}/experiments")
    public ApiResponse<List<ExperimentSummaryResponse>> list(@LoginMember Long memberId, @PathVariable Long reviewId) {
        return ApiResponse.of(experimentService.list(memberId, reviewId));
    }
}
