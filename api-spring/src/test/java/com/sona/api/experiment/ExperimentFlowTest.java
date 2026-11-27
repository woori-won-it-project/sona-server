package com.sona.api.experiment;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

/**
 * 기능 7 흐름: 페르소나 선택 → 실험 시작(202) → 완료 → 응답 조회 → 잠금.
 * mock 프로필이라 AI 는 MockPersonaAi (실제 호출 없음). 검수 3 (mock/data.sql) 을 쓴다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("mock")
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
class ExperimentFlowTest {

    @Autowired
    MockMvc mockMvc;

    @Autowired
    ObjectMapper objectMapper;

    @Test
    void 페르소나_선택부터_실험_완료까지() throws Exception {
        // 페르소나를 고르기 전에는 실험을 시작할 수 없다
        startInitial(3)
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("PERSONA_NOT_SELECTED"));

        // 페르소나 목록: 새 속성이 보이고 prompt 는 안 보인다
        mockMvc.perform(get("/api/v1/personas"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].ageGroup").value("SIXTIES"))
                .andExpect(jsonPath("$.data[0].infoPath").value("AGENT_TALK"))
                .andExpect(jsonPath("$.data[0].prompt").doesNotExist());

        // 설계사 설명(1), 설명서 직접 - 용어 이해 하(2)·중(6)·상(10)
        mockMvc.perform(put("/api/v1/reviews/3/personas")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"personaIds\":[1,2,6,10]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.selectedCount").value(4));

        String body = startInitial(3)
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.data.status").value("RUNNING"))
                .andExpect(jsonPath("$.data.totalResponses").value(12))
                .andReturn()
                .getResponse()
                .getContentAsString();
        long experimentId = objectMapper.readTree(body).at("/data/experimentId").asLong();

        assertThat(waitUntilDone(experimentId)).isEqualTo("COMPLETED");

        // 응답: 4명 x 3문항, 모두 3지선다 보기를 골랐고 채점됐다
        JsonNode data = objectMapper
                .readTree(mockMvc.perform(get("/api/v1/experiments/" + experimentId + "/responses"))
                        .andExpect(status().isOk())
                        .andReturn()
                        .getResponse()
                        .getContentAsString())
                .get("data");
        assertThat(data).hasSize(4);
        for (JsonNode persona : data) {
            assertThat(persona.get("readingMemo").asText()).isNotBlank();
            assertThat(persona.get("responses")).hasSize(3);
            for (JsonNode r : persona.get("responses")) {
                assertThat(r.get("selectedOption").asText()).isIn("A", "B", "C");
                assertThat(r.get("selectedOptionText").asText()).isNotBlank();
                assertThat(r.get("gradingResult").asText()).isIn("CORRECT", "INCORRECT");
            }
        }

        // 실험 목록에 오해율이 나온다
        mockMvc.perform(get("/api/v1/reviews/3/experiments"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].experimentId").value(experimentId))
                .andExpect(jsonPath("$.data[0].documentVersion").value(1))
                .andExpect(jsonPath("$.data[0].misunderstandingRate").isNumber());

        // 첫 실험 뒤에는 페르소나를 바꿀 수 없고, 첫 실험을 또 할 수 없다
        mockMvc.perform(put("/api/v1/reviews/3/personas")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"personaIds\":[1]}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("REVIEW_LOCKED"));
        startInitial(3)
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("INITIAL_EXPERIMENT_EXISTS"));
    }

    @Test
    void 없는_검수는_404() throws Exception {
        mockMvc.perform(get("/api/v1/reviews/999/experiments"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("NOT_FOUND"));
    }

    @Test
    void 재실험인데_새_설명서가_없으면_NEW_DOCUMENT_REQUIRED() throws Exception {
        // 검수 1: 최신 설명서 V2 를 이미 실험 2 에서 썼다
        mockMvc.perform(post("/api/v1/reviews/1/experiments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"experimentType\":\"RERUN\",\"parentExperimentId\":2}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("NEW_DOCUMENT_REQUIRED"));
    }

    private ResultActions startInitial(long reviewId) throws Exception {
        return mockMvc.perform(post("/api/v1/reviews/" + reviewId + "/experiments")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"experimentType\":\"INITIAL\",\"parentExperimentId\":null}"));
    }

    private String waitUntilDone(long experimentId) throws Exception {
        String status = "RUNNING";
        for (int i = 0; i < 100 && "RUNNING".equals(status); i++) {
            Thread.sleep(100);
            String body = mockMvc.perform(get("/api/v1/experiments/" + experimentId))
                    .andReturn()
                    .getResponse()
                    .getContentAsString();
            status = objectMapper.readTree(body).at("/data/status").asText();
        }
        return status;
    }
}
