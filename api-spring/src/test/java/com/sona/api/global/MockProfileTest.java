package com.sona.api.global;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.sona.api.experiment.domain.ExperimentResponse;
import com.sona.api.experiment.domain.ExperimentResponseRepository;
import com.sona.api.review.domain.ReviewRepository;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

/**
 * mock 프로필(H2 + 목업 데이터) 확인.
 * 기동 자체가 Entity 와 mock/schema.sql 이 맞는지 검사한다 (ddl-auto: validate).
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("mock")
class MockProfileTest {

    @Autowired
    MockMvc mockMvc;

    @Autowired
    ReviewRepository reviewRepository;

    @Autowired
    ExperimentResponseRepository experimentResponseRepository;

    @Test
    void 목업_데이터가_들어간다() {
        assertThat(reviewRepository.count()).isEqualTo(2);
        assertThat(experimentResponseRepository.count()).isEqualTo(18);
    }

    @Test
    @Transactional
    void 첫_실험_오해율은_오답과_판단불가를_센다() {
        List<ExperimentResponse> responses = experimentResponseRepository.findByExperimentId(1L);
        long misunderstood =
                responses.stream().filter(ExperimentResponse::isMisunderstood).count();
        assertThat(responses).hasSize(9);
        assertThat(misunderstood).isEqualTo(3); // 오답 1 + 판단 불가 2
    }

    @Test
    void 로그인하면_data_로_감싼_토큰을_준다() throws Exception {
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"employeeNumber\":\"EMP001\",\"password\":\"password123\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.accessToken").value("mock-1"))
                .andExpect(jsonPath("$.data.tokenType").value("Bearer"))
                .andExpect(jsonPath("$.data.member.name").value("홍길동"));
    }

    @Test
    void 비밀번호가_틀리면_LOGIN_FAILED() throws Exception {
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"employeeNumber\":\"EMP001\",\"password\":\"wrong\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("LOGIN_FAILED"));
    }

    @Test
    void 입력이_비면_필드별_이유를_준다() throws Exception {
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"employeeNumber\":\"\",\"password\":\"x\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"))
                .andExpect(jsonPath("$.details.employeeNumber").exists());
    }

    @Test
    void 틀린_토큰이면_UNAUTHORIZED() throws Exception {
        mockMvc.perform(post("/api/v1/auth/logout").header("Authorization", "Bearer wrong"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHORIZED"));
    }

    @Test
    void 없는_주소는_NOT_FOUND() throws Exception {
        mockMvc.perform(get("/api/v1/nothing"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("NOT_FOUND"));
    }

    @Test
    void Swagger_문서가_열린다() throws Exception {
        mockMvc.perform(get("/v3/api-docs")).andExpect(status().isOk());
    }
}
