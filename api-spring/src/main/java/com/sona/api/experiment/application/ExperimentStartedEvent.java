package com.sona.api.experiment.application;

/** 실험 행이 저장(커밋)된 뒤 백그라운드 실행을 시작하라는 신호 */
public record ExperimentStartedEvent(Long experimentId) {}
