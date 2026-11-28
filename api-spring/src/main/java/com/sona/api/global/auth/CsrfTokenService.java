package com.sona.api.global.auth;

import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

public final class CsrfTokenService {

    public static final String HEADER = "X-XSRF-TOKEN";
    private static final String ALGORITHM = "HmacSHA256";
    private static final int ENCODED_LENGTH = 43;
    private static final Base64.Encoder ENCODER = Base64.getUrlEncoder().withoutPadding();

    private final SecretKeySpec key;
    private final SecureRandom random = new SecureRandom();

    public CsrfTokenService(byte[] key) {
        if (key == null || key.length < 32) {
            throw new IllegalArgumentException("CSRF requires a key of at least 256 bits");
        }
        this.key = new SecretKeySpec(key, ALGORITHM);
    }

    public String issue() {
        byte[] nonce = new byte[32];
        random.nextBytes(nonce);
        String payload = ENCODER.encodeToString(nonce);
        return payload + "." + signature(payload);
    }

    public void verify(HttpServletRequest request) {
        var headers = request.getHeaders(HEADER);
        String header = headers.hasMoreElements() ? headers.nextElement() : null;
        String cookie = AuthCookies.read(request, AuthCookies.CSRF);
        if (header == null
                || headers.hasMoreElements()
                || cookie == null
                || header.length() != ENCODED_LENGTH * 2 + 1
                || cookie.length() != header.length()
                || header.charAt(ENCODED_LENGTH) != '.'
                || !equal(header, cookie)
                || !equal(signature(header.substring(0, ENCODED_LENGTH)), header.substring(ENCODED_LENGTH + 1))) {
            throw new BusinessException(ErrorCode.INVALID_CSRF_TOKEN);
        }
    }

    private String signature(String payload) {
        try {
            Mac mac = Mac.getInstance(ALGORITHM);
            mac.init(key);
            return ENCODER.encodeToString(mac.doFinal(payload.getBytes(StandardCharsets.UTF_8)));
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("CSRF signing failed");
        }
    }

    private static boolean equal(String first, String second) {
        return MessageDigest.isEqual(first.getBytes(StandardCharsets.UTF_8), second.getBytes(StandardCharsets.UTF_8));
    }
}
