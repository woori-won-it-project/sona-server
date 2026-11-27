package com.sona.api.persona.engine;

import com.sona.api.persona.domain.Disposition;
import com.sona.api.persona.domain.FinancialLiteracy;

/** 읽기 규칙에 필요한 페르소나 값만 모은 것. seed 는 페르소나 id (같은 사람은 언제나 같은 방식으로 읽는다). */
public record PersonaProfile(long seed, FinancialLiteracy literacy, double diligence, Disposition disposition) {}
