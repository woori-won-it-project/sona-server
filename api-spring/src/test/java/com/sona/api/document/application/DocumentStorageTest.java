package com.sona.api.document.application;

import static com.sona.api.document.application.DocumentStorage.FailureReason.ACCESS_DENIED;
import static com.sona.api.document.application.DocumentStorage.FailureReason.ALREADY_EXISTS;
import static com.sona.api.document.application.DocumentStorage.FailureReason.FAILED;
import static com.sona.api.document.application.DocumentStorage.FailureReason.OUTCOME_UNKNOWN;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.sona.api.document.application.DocumentStorage.Metadata;
import com.sona.api.document.application.DocumentStorage.StorageException;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class DocumentStorageTest {

    private static final String KEY = "review-documents/request-id/terms.pdf";

    private final InMemoryDocumentStorage storage = new InMemoryDocumentStorage();

    @Test
    void 원본_바이트와_업로드_표식을_보존하고_스트림은_소유자가_닫는다() throws IOException {
        byte[] content = {1, 2, 3};
        var upload = new TrackedInputStream(content);
        storage.put(KEY, content.length, "attempt-1", () -> upload);

        assertThat(upload.closed).isTrue();
        assertThat(storage.head(KEY)).contains(new Metadata(3L, Optional.of("attempt-1")));

        var download = (TrackedInputStream) storage.get(KEY).orElseThrow();
        assertThat(download.closed).isFalse();
        try (download) {
            assertThat(download.readAllBytes()).containsExactly(content);
        }
        assertThat(download.closed).isTrue();
    }

    @Test
    void 빈_객체_부재_조회_실패를_구분한다() throws IOException {
        assertThat(storage.head(KEY)).isEmpty();
        assertThat(storage.get(KEY)).isEmpty();

        storage.put(KEY, 0L, "empty", InputStream::nullInputStream);
        assertThat(storage.head(KEY)).contains(new Metadata(0L, Optional.of("empty")));
        try (var empty = storage.get(KEY).orElseThrow()) {
            assertThat(empty.read()).isEqualTo(-1);
        }

        storage.headDenied = true;
        assertThatThrownBy(() -> storage.head(KEY)).isInstanceOfSatisfying(StorageException.class, exception -> {
            assertThat(exception.reason()).isEqualTo(ACCESS_DENIED);
        });
    }

    @Test
    void 메타데이터는_long_바이트_길이와_표식_없는_기존_객체를_표현한다() {
        long length = 1L << 32;
        var metadata = new Metadata(length, Optional.empty());

        assertThat(metadata.contentLength()).isEqualTo(length);
        assertThat(metadata.uploadMarker()).isEmpty();
        assertThatThrownBy(() -> new Metadata(-1L, Optional.empty())).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void 같은_키로_다시_업로드해도_기존_객체를_덮어쓰지_않는다() throws IOException {
        storage.put(KEY, 1L, "original", () -> new ByteArrayInputStream(new byte[] {1}));

        assertThatThrownBy(() -> storage.put(KEY, 0L, "replacement", InputStream::nullInputStream))
                .isInstanceOfSatisfying(StorageException.class, exception -> {
                    assertThat(exception.reason()).isEqualTo(ALREADY_EXISTS);
                });
        assertThat(storage.head(KEY)).contains(new Metadata(1L, Optional.of("original")));
    }

    @Test
    void 삭제_응답이_유실되면_결과_미확정으로_알리고_재호출을_허용한다() throws IOException {
        storage.put(KEY, 0L, "attempt-1", InputStream::nullInputStream);
        storage.loseNextDeleteResponse = true;

        assertThatThrownBy(() -> storage.delete(KEY)).isInstanceOfSatisfying(StorageException.class, exception -> {
            assertThat(exception.reason()).isEqualTo(OUTCOME_UNKNOWN);
        });
        storage.delete(KEY);
        storage.delete(KEY);

        assertThat(storage.head(KEY)).isEmpty();
        assertThat(storage.get(KEY)).isEmpty();
    }

    private static final class InMemoryDocumentStorage implements DocumentStorage {
        private final Map<String, StoredDocument> objects = new HashMap<>();
        private boolean headDenied;
        private boolean loseNextDeleteResponse;

        @Override
        public void put(String key, long contentLength, String uploadMarker, UploadSource source)
                throws StorageException {
            if (objects.containsKey(key)) {
                throw new StorageException(ALREADY_EXISTS, null);
            }
            byte[] bytes;
            try (var stream = source.open()) {
                bytes = stream.readAllBytes();
            } catch (IOException failure) {
                throw new StorageException(FAILED, failure);
            }
            if (bytes.length != contentLength) {
                throw new StorageException(FAILED, null);
            }
            objects.put(key, new StoredDocument(new Metadata(contentLength, Optional.of(uploadMarker)), bytes));
        }

        @Override
        public Optional<InputStream> get(String key) {
            return Optional.ofNullable(objects.get(key)).map(document -> new TrackedInputStream(document.content()));
        }

        @Override
        public Optional<Metadata> head(String key) throws StorageException {
            if (headDenied) {
                throw new StorageException(ACCESS_DENIED, null);
            }
            return Optional.ofNullable(objects.get(key)).map(StoredDocument::metadata);
        }

        @Override
        public void delete(String key) throws StorageException {
            objects.remove(key);
            if (loseNextDeleteResponse) {
                loseNextDeleteResponse = false;
                throw new StorageException(OUTCOME_UNKNOWN, null);
            }
        }

        private record StoredDocument(Metadata metadata, byte[] content) {}
    }

    private static final class TrackedInputStream extends ByteArrayInputStream {
        private boolean closed;

        private TrackedInputStream(byte[] buffer) {
            super(buffer);
        }

        @Override
        public void close() throws IOException {
            closed = true;
            super.close();
        }
    }
}
