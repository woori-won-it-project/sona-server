package com.sona.api.experiment.domain;

/** 첫 실험 / 재실험. DB 컬럼은 없고 parent_experiment_id 가 null 인지로 정한다 (api.md 20) */
public enum ExperimentType {
    INITIAL,
    RERUN
}
