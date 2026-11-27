package com.sona.api.persona.api;

import com.sona.api.global.auth.LoginMember;
import com.sona.api.global.response.ApiResponse;
import com.sona.api.persona.application.PersonaService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "7. 페르소나 · 실험", description = "페르소나 목록·선택, 실험 시작·조회")
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class PersonaController {

    private final PersonaService personaService;

    @Operation(summary = "페르소나 목록 (18)")
    @GetMapping("/personas")
    public ApiResponse<List<PersonaResponse>> list(@LoginMember Long memberId) {
        return ApiResponse.of(personaService.list());
    }

    @Operation(summary = "검수별 페르소나 선택 (19)", description = "보낸 목록 전체로 덮어쓴다. 첫 실험 뒤에는 409 REVIEW_LOCKED")
    @PutMapping("/reviews/{reviewId}/personas")
    public ApiResponse<SelectPersonasResponse> select(
            @LoginMember Long memberId,
            @PathVariable Long reviewId,
            @Valid @RequestBody SelectPersonasRequest request) {
        return ApiResponse.of(personaService.select(memberId, reviewId, request.personaIds()));
    }
}
