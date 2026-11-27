package com.sona.api.persona.api;

import com.sona.api.persona.domain.AgeGroup;
import com.sona.api.persona.domain.Disposition;
import com.sona.api.persona.domain.FinancialLiteracy;
import com.sona.api.persona.domain.InfoPath;
import com.sona.api.persona.domain.Persona;
import java.math.BigDecimal;

/** api.md 18. prompt 는 넣지 않는다. 나이대·꼼꼼함·정보 경로·성향은 spec 4.7.1 로 새로 붙은 값 */
public record PersonaResponse(
        Long personaId,
        String name,
        FinancialLiteracy financialLiteracy,
        String readingBehavior,
        String description,
        AgeGroup ageGroup,
        BigDecimal diligence,
        InfoPath infoPath,
        Disposition disposition) {

    public static PersonaResponse from(Persona p) {
        return new PersonaResponse(
                p.getId(),
                p.getName(),
                p.getFinancialLiteracy(),
                p.getReadingBehavior(),
                p.getDescription(),
                p.getAgeGroup(),
                p.getDiligence(),
                p.getInfoPath(),
                p.getDisposition());
    }
}
