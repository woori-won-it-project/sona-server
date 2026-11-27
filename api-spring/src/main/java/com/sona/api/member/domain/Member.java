package com.sona.api.member.domain;

import com.sona.api.global.entity.BaseCreatedEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** 회원 (담당자). 사번으로 로그인한다. */
@Getter
@Entity
@Table(name = "members")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Member extends BaseCreatedEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "employee_number", nullable = false, unique = true, length = 30)
    private String employeeNumber;

    @Column(nullable = false, length = 50)
    private String name;

    /** 해시 종류가 앞에 붙은 값. 예: {bcrypt}... (Spring DelegatingPasswordEncoder 형식) */
    @Column(name = "password_hash", nullable = false)
    private String passwordHash;

    @Builder
    private Member(String employeeNumber, String name, String passwordHash) {
        this.employeeNumber = employeeNumber;
        this.name = name;
        this.passwordHash = passwordHash;
    }
}
