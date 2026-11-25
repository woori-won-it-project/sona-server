# ---- build ----
FROM eclipse-temurin:21-jdk AS build
WORKDIR /app
# 이미지 빌드 중에는 spotlessApply(자동 정렬)를 돌리지 않는다. 정렬은 로컬에서 끝난 코드만 들어온다는 전제
ENV CI=true

COPY gradlew settings.gradle build.gradle ./
COPY gradle gradle
RUN chmod +x gradlew && ./gradlew dependencies --no-daemon > /dev/null

COPY src src
RUN ./gradlew bootJar --no-daemon

# ---- runtime ----
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /app/build/libs/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
