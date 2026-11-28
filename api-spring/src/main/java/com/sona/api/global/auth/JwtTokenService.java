package com.sona.api.global.auth;

import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JOSEObjectType;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jose.crypto.MACVerifier;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.ParseException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/** Explicitly constructed by the authentication entry point once profile configuration is available. */
public final class JwtTokenService {

    private static final int MAX_TOKEN_LENGTH = 4096;
    private static final String SESSION_ID = "sid";
    private static final String TOKEN_USE = "token_use";
    private static final JWSHeader HEADER =
            new JWSHeader.Builder(JWSAlgorithm.HS256).type(JOSEObjectType.JWT).build();

    private final AuthProperties properties;
    private final Clock clock;
    private final MACSigner signer;
    private final MACVerifier verifier;

    public JwtTokenService(AuthProperties properties, byte[] signingKey, Clock clock) {
        this.properties = Objects.requireNonNull(properties);
        this.clock = Objects.requireNonNull(clock);
        if (signingKey == null || signingKey.length < 32) {
            throw new IllegalArgumentException("HS256 requires a key of at least 256 bits");
        }
        byte[] key = signingKey.clone();
        try {
            signer = new MACSigner(key);
            verifier = new MACVerifier(key);
        } catch (JOSEException e) {
            throw new IllegalArgumentException("Invalid JWT signing key");
        }
    }

    public TokenPair issue(long memberId) {
        if (memberId <= 0) {
            throw new IllegalArgumentException("Member ID must be positive");
        }
        Instant now = now();
        return issuePair(memberId, UUID.randomUUID(), now, now.plus(AuthProperties.SESSION_LIFETIME));
    }

    /** Prepares replacement credentials. Callers must return them only after the Redis compare-and-set succeeds. */
    public Optional<TokenPair> prepareRotation(VerifiedToken refresh) {
        refresh.requireUse(TokenUse.REFRESH);
        Instant now = now();
        if (!refresh.expiresAt().isAfter(now)) {
            return Optional.empty();
        }
        return Optional.of(issuePair(refresh.memberId(), refresh.sessionId(), now, refresh.expiresAt()));
    }

    public Optional<VerifiedToken> verifyAccess(String token) {
        return verify(token, TokenUse.ACCESS);
    }

    public Optional<VerifiedToken> verifyRefresh(String token) {
        return verify(token, TokenUse.REFRESH);
    }

    private TokenPair issuePair(long memberId, UUID sid, Instant now, Instant sessionExpiry) {
        Instant accessExpiry = now.plus(AuthProperties.ACCESS_LIFETIME);
        if (accessExpiry.isAfter(sessionExpiry)) {
            accessExpiry = sessionExpiry;
        }
        return new TokenPair(
                issueToken(memberId, sid, now, accessExpiry, TokenUse.ACCESS),
                issueToken(memberId, sid, now, sessionExpiry, TokenUse.REFRESH));
    }

    private IssuedToken issueToken(long memberId, UUID sid, Instant now, Instant expiresAt, TokenUse use) {
        UUID jti = UUID.randomUUID();
        JWTClaimsSet claims = new JWTClaimsSet.Builder()
                .issuer(properties.issuer())
                .audience(properties.audience())
                .subject(Long.toString(memberId))
                .jwtID(jti.toString())
                .claim(SESSION_ID, sid.toString())
                .claim(TOKEN_USE, use.claim)
                .issueTime(Date.from(now))
                .expirationTime(Date.from(expiresAt))
                .build();
        SignedJWT jwt = new SignedJWT(HEADER, claims);
        try {
            jwt.sign(signer);
        } catch (JOSEException e) {
            throw new IllegalStateException("JWT signing failed");
        }
        String value = jwt.serialize();
        return new IssuedToken(value, verifiedClaims(value, memberId, sid, jti, expiresAt, use));
    }

    private Optional<VerifiedToken> verify(String value, TokenUse use) {
        if (value == null || value.isBlank() || value.length() > MAX_TOKEN_LENGTH) {
            return Optional.empty();
        }
        try {
            SignedJWT jwt = SignedJWT.parse(value);
            if (!JWSAlgorithm.HS256.equals(jwt.getHeader().getAlgorithm())
                    || !JOSEObjectType.JWT.equals(jwt.getHeader().getType())
                    || !jwt.verify(verifier)) {
                return Optional.empty();
            }
            JWTClaimsSet claims = jwt.getJWTClaimsSet();
            if (!properties.issuer().equals(claims.getIssuer())
                    || !List.of(properties.audience()).equals(claims.getAudience())
                    || !use.claim.equals(claims.getStringClaim(TOKEN_USE))
                    || claims.getIssueTime() == null
                    || claims.getExpirationTime() == null) {
                return Optional.empty();
            }
            Instant now = now();
            Instant issuedAt = claims.getIssueTime().toInstant();
            Instant expiresAt = claims.getExpirationTime().toInstant();
            if (issuedAt.isAfter(now)
                    || !expiresAt.isAfter(now)
                    || !expiresAt.isAfter(issuedAt)
                    || Duration.between(issuedAt, expiresAt).compareTo(use.lifetime) > 0
                    || (claims.getNotBeforeTime() != null
                            && claims.getNotBeforeTime().toInstant().isAfter(now))) {
                return Optional.empty();
            }
            long memberId = Long.parseLong(claims.getSubject());
            if (memberId <= 0 || !Long.toString(memberId).equals(claims.getSubject())) {
                return Optional.empty();
            }
            UUID sid = parseId(claims.getStringClaim(SESSION_ID));
            UUID jti = parseId(claims.getJWTID());
            return Optional.of(verifiedClaims(value, memberId, sid, jti, expiresAt, use));
        } catch (ParseException | JOSEException | IllegalArgumentException e) {
            return Optional.empty();
        }
    }

    private Instant now() {
        return clock.instant().truncatedTo(ChronoUnit.SECONDS);
    }

    private static UUID parseId(String value) {
        if (value == null || value.length() != 36) {
            throw new IllegalArgumentException("JWT ID must be a UUID");
        }
        UUID id = UUID.fromString(value);
        if (!id.toString().equals(value)) {
            throw new IllegalArgumentException("JWT ID must use canonical UUID format");
        }
        return id;
    }

    private static VerifiedToken verifiedClaims(
            String value, long memberId, UUID sid, UUID jti, Instant expiresAt, TokenUse use) {
        String hash = use == TokenUse.REFRESH ? sha256(value) : null;
        return new VerifiedToken(memberId, sid, jti, expiresAt, use, hash);
    }

    private static String sha256(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        }
    }

    enum TokenUse {
        ACCESS("access", AuthProperties.ACCESS_LIFETIME),
        REFRESH("refresh", AuthProperties.SESSION_LIFETIME);

        private final String claim;
        private final Duration lifetime;

        TokenUse(String claim, Duration lifetime) {
            this.claim = claim;
            this.lifetime = lifetime;
        }
    }

    public record TokenPair(IssuedToken access, IssuedToken refresh) {}

    public record IssuedToken(String value, VerifiedToken claims) {
        @Override
        public String toString() {
            return "IssuedToken[redacted]";
        }
    }

    public static final class VerifiedToken {
        private final long memberId;
        private final UUID sessionId;
        private final UUID tokenId;
        private final Instant expiresAt;
        private final TokenUse use;
        private final String refreshHash;

        private VerifiedToken(
                long memberId, UUID sessionId, UUID tokenId, Instant expiresAt, TokenUse use, String refreshHash) {
            this.memberId = memberId;
            this.sessionId = sessionId;
            this.tokenId = tokenId;
            this.expiresAt = expiresAt;
            this.use = use;
            this.refreshHash = refreshHash;
        }

        public long memberId() {
            return memberId;
        }

        public UUID sessionId() {
            return sessionId;
        }

        public UUID tokenId() {
            return tokenId;
        }

        public Instant expiresAt() {
            return expiresAt;
        }

        String refreshHash() {
            requireUse(TokenUse.REFRESH);
            return refreshHash;
        }

        void requireUse(TokenUse expected) {
            if (use != expected) {
                throw new IllegalArgumentException("Unexpected JWT use");
            }
        }
    }
}
