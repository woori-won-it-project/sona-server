package com.sona.api.persona.engine;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * 같은 사람(seed)·같은 표시(tag)면 언제나 같은 0~1 난수.
 * 문장 읽기는 tag 에 문장 글자를 넣어서, 재실험에서 바뀌지 않은 문장은 똑같이 읽고 바뀐 문장만 새로 정해지게 한다.
 */
public final class SeededRandom {

    private SeededRandom() {}

    public static double next(long seed, String tag) {
        try {
            byte[] h = MessageDigest.getInstance("SHA-256").digest((seed + ":" + tag).getBytes(StandardCharsets.UTF_8));
            long v = 0;
            for (int i = 0; i < 7; i++) {
                v = (v << 8) | (h[i] & 0xff);
            }
            return (double) v / (1L << 56);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
