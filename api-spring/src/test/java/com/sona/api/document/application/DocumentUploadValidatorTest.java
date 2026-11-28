package com.sona.api.document.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import jakarta.servlet.http.Part;
import java.io.InputStream;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.mock.web.MockPart;

class DocumentUploadValidatorTest {

    private static final long LIMIT = 20_971_520L;

    private final DocumentUploadValidator validator = new DocumentUploadValidator();

    @ParameterizedTest
    @CsvSource({"1, 1", "20971519, 20971520", "20971520, 20971519", "20971520, 20971520"})
    void 지정된_두_파트를_파일당_20MiB까지_허용한다(long termsSize, long guideSize) {
        Part terms = terms(termsSize);
        Part guide = guide(guideSize);

        var result = validator.validate(List.of(guide, terms));

        assertThat(result.terms()).isSameAs(terms);
        assertThat(result.productGuide()).isSameAs(guide);
        assertThat(result.productGuide().getSubmittedFileName()).isEqualTo("상품설명서");
    }

    @ParameterizedTest
    @ValueSource(longs = {LIMIT + 1, 1L << 32})
    void 어느_파일이든_한도를_넘으면_거절한다(long size) {
        assertError(ErrorCode.FILE_TOO_LARGE, terms(size), guide(1));
        assertError(ErrorCode.FILE_TOO_LARGE, terms(1), guide(size));
    }

    @Test
    void 필수_파일_누락과_빈_파일을_거절한다() {
        assertError(ErrorCode.REQUIRED_DOCUMENT_MISSING);
        assertError(ErrorCode.REQUIRED_DOCUMENT_MISSING, terms(1));
        assertError(ErrorCode.REQUIRED_DOCUMENT_MISSING, guide(1));
        assertError(ErrorCode.REQUIRED_DOCUMENT_MISSING, terms(0), guide(1));
        assertError(ErrorCode.REQUIRED_DOCUMENT_MISSING, terms(1), guide(0));
        assertError(ErrorCode.REQUIRED_DOCUMENT_MISSING, file("terms", "", 0), guide(1));
    }

    @Test
    void 중복과_등록_대상이_아닌_파트를_거절한다() {
        assertError(ErrorCode.INVALID_INPUT, terms(1), guide(1), terms(0));
        assertError(ErrorCode.INVALID_INPUT, terms(1), guide(1), guide(1));
        assertError(ErrorCode.INVALID_INPUT, terms(1), guide(1), file("specialTerms", "특약", 1));
        assertError(ErrorCode.INVALID_INPUT, terms(1), guide(1), new MockPart("note", new byte[] {1}));
    }

    @Test
    void 파일이_아닌_필수_파트와_비정상_파일_정보를_거절한다() {
        assertError(ErrorCode.INVALID_INPUT, new MockPart("terms", new byte[] {1}), guide(1));
        assertError(ErrorCode.INVALID_INPUT, terms(1), guide(1), new MockPart("productGuide", new byte[] {1}));
        assertError(ErrorCode.INVALID_INPUT, terms(1), file("productGuide", "", 1));
        assertError(ErrorCode.INVALID_INPUT, terms(1), file("productGuide", " ", 1));
        assertError(ErrorCode.INVALID_INPUT, terms(-1), guide(1));
    }

    private void assertError(ErrorCode error, Part... parts) {
        assertThatThrownBy(() -> validator.validate(List.of(parts)))
                .isInstanceOfSatisfying(BusinessException.class, exception -> {
                    assertThat(exception.getErrorCode()).isEqualTo(error);
                });
    }

    private Part terms(long size) {
        return file("terms", "보험약관", size);
    }

    private Part guide(long size) {
        return file("productGuide", "상품설명서", size);
    }

    private Part file(String fieldName, String filename, long size) {
        return new MockPart(fieldName, filename, new byte[0]) {
            @Override
            public long getSize() {
                return size;
            }

            @Override
            public InputStream getInputStream() {
                throw new AssertionError("파트 검증에서 파일 내용을 열지 않습니다.");
            }
        };
    }
}
