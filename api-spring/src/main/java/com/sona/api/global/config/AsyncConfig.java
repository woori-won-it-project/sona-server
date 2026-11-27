package com.sona.api.global.config;

import java.util.concurrent.Executor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

/** 실험 백그라운드 실행용 스레드 풀. 실험 하나 = experimentExecutor 1개, 그 안의 페르소나들은 personaExecutor 에서 동시에. */
@EnableAsync
@Configuration
public class AsyncConfig {

    @Bean(name = "experimentExecutor")
    public Executor experimentExecutor() {
        return pool("experiment-", 2, 4, 20);
    }

    @Bean(name = "personaExecutor")
    public Executor personaExecutor() {
        return pool("persona-", 4, 4, 200);
    }

    private static ThreadPoolTaskExecutor pool(String prefix, int core, int max, int queue) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setThreadNamePrefix(prefix);
        executor.setCorePoolSize(core);
        executor.setMaxPoolSize(max);
        executor.setQueueCapacity(queue);
        executor.initialize();
        return executor;
    }
}
