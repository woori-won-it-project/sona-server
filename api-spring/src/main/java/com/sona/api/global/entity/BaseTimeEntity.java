package com.sona.api.global.entity;

import jakarta.persistence.Column;
import jakarta.persistence.MappedSuperclass;
import java.time.LocalDateTime;
import lombok.Getter;
import org.hibernate.annotations.UpdateTimestamp;

/** created_at, updated_at 이 둘 다 있는 테이블의 공통 부모. */
@Getter
@MappedSuperclass
public abstract class BaseTimeEntity extends BaseCreatedEntity {

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;
}
