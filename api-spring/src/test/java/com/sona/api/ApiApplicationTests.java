package com.sona.api;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

/**
 * 컨텍스트 기동 테스트. test 프로필로 실제 PostgreSQL(init.sql 적용된 DB)에 붙어
 * ddl-auto: validate 로 Entity 와 스키마가 맞는지 확인한다.
 */
@SpringBootTest
@ActiveProfiles("test")
class ApiApplicationTests {

    @Test
    void contextLoads() {
    }

}
