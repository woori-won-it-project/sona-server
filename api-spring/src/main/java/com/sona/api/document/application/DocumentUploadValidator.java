package com.sona.api.document.application;

import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import jakarta.servlet.http.Part;
import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

/** 파싱된 multipart 요청에서 최초 등록에 필요한 파일 파트와 크기를 검증한다. */
public class DocumentUploadValidator {

    private static final String TERMS = "terms";
    private static final String PRODUCT_GUIDE = "productGuide";
    private static final long MAX_FILE_SIZE = 20L * 1024 * 1024;

    public ValidatedParts validate(Collection<Part> parts) {
        Map<String, Part> files = new HashMap<>();
        for (Part part : parts) {
            String name = part.getName();
            if ((!TERMS.equals(name) && !PRODUCT_GUIDE.equals(name))
                    || part.getSubmittedFileName() == null
                    || files.putIfAbsent(name, part) != null) {
                throw new BusinessException(ErrorCode.INVALID_INPUT);
            }
        }

        Part terms = files.get(TERMS);
        Part productGuide = files.get(PRODUCT_GUIDE);
        validateFile(terms);
        validateFile(productGuide);
        return new ValidatedParts(terms, productGuide);
    }

    private void validateFile(Part part) {
        if (part == null) {
            throw new BusinessException(ErrorCode.REQUIRED_DOCUMENT_MISSING);
        }
        long size = part.getSize();
        if (size == 0) {
            throw new BusinessException(ErrorCode.REQUIRED_DOCUMENT_MISSING);
        }
        if (part.getSubmittedFileName().isBlank() || size < 0) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
        if (size > MAX_FILE_SIZE) {
            throw new BusinessException(ErrorCode.FILE_TOO_LARGE);
        }
    }

    public record ValidatedParts(Part terms, Part productGuide) {}
}
