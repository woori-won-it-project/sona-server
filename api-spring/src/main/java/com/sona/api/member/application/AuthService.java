package com.sona.api.member.application;

import com.sona.api.global.error.BusinessException;
import com.sona.api.global.error.ErrorCode;
import com.sona.api.member.api.LoginResponse.MemberInfo;
import com.sona.api.member.domain.Member;
import com.sona.api.member.domain.MemberRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.factory.PasswordEncoderFactories;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AuthService {

    /** {bcrypt}, {noop} 등 해시 종류가 앞에 붙은 값을 모두 비교할 수 있다. */
    private static final PasswordEncoder PASSWORD_ENCODER = PasswordEncoderFactories.createDelegatingPasswordEncoder();

    private final MemberRepository memberRepository;

    public MemberInfo authenticate(String employeeNumber, String password) {
        // 사번이 없을 때와 비밀번호가 틀렸을 때 같은 에러: 어느 쪽이 틀렸는지 알려 주지 않는다
        Member member = memberRepository
                .findByEmployeeNumber(employeeNumber)
                .filter(m -> PASSWORD_ENCODER.matches(password, m.getPasswordHash()))
                .orElseThrow(() -> new BusinessException(ErrorCode.LOGIN_FAILED));

        return new MemberInfo(member.getId(), member.getEmployeeNumber(), member.getName());
    }
}
