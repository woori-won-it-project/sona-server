package com.sona.api.document.application;

import java.io.IOException;
import java.io.InputStream;
import java.util.Objects;
import java.util.Optional;

/** 문서 원본 저장소. 키는 서버가 생성하며 버킷 내부 경로로 해석한다. */
public interface DocumentStorage {

    /**
     * PDF 원본을 지정 키에 생성한다. 길이 단위는 바이트이며 기존 객체는 덮어쓰지 않는다.
     * 구현체가 열어 사용한 스트림을 닫는다. 재시도할 때 source는 처음부터 읽을 새 스트림을 제공해야 한다.
     * uploadMarker는 응답이 유실된 경우 Head로 업로드 시도를 확인하기 위한 식별자다.
     */
    void put(String key, long contentLength, String uploadMarker, UploadSource source) throws StorageException;

    /**
     * 존재가 확인된 원본의 스트림을 반환한다. 호출자가 스트림을 닫으며 읽기 중 I/O 오류도 처리한다.
     * 객체 부재가 확인된 경우에만 빈 Optional을 반환한다.
     */
    Optional<InputStream> get(String key) throws StorageException;

    /** 객체 부재가 확인된 경우에만 빈 Optional을 반환한다. 0바이트는 유효한 객체 길이다. */
    Optional<Metadata> head(String key) throws StorageException;

    /** 정상 반환하면 키로 객체를 더 이상 조회할 수 없다. 이미 없는 키도 정상 처리한다. */
    void delete(String key) throws StorageException;

    @FunctionalInterface
    interface UploadSource {
        InputStream open() throws IOException;
    }

    /** uploadMarker가 없는 기존 객체도 조회할 수 있다. */
    record Metadata(long contentLength, Optional<String> uploadMarker) {
        public Metadata {
            if (contentLength < 0) {
                throw new IllegalArgumentException("객체 길이는 음수일 수 없습니다.");
            }
            Objects.requireNonNull(uploadMarker);
        }
    }

    enum FailureReason {
        ALREADY_EXISTS,
        ACCESS_DENIED,
        FAILED,
        /** Put이나 Delete가 적용됐는지 확인할 수 없으며 확인 또는 재시도가 필요하다. */
        OUTCOME_UNKNOWN
    }

    class StorageException extends IOException {
        private final FailureReason reason;

        public StorageException(FailureReason reason, Throwable cause) {
            super(reason.name(), cause);
            this.reason = reason;
        }

        public FailureReason reason() {
            return reason;
        }
    }
}
