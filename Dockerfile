FROM eclipse-temurin:17-jdk-jammy AS android-build

ARG ANDROID_COMMAND_LINE_TOOLS=11076708
ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    PATH="/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:$PATH"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends curl unzip \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p "$ANDROID_HOME/cmdline-tools" \
    && curl --fail --location --silent --show-error \
        "https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_COMMAND_LINE_TOOLS}_latest.zip" \
        --output /tmp/android-tools.zip \
    && unzip -q /tmp/android-tools.zip -d /tmp/android-tools \
    && mv /tmp/android-tools/cmdline-tools "$ANDROID_HOME/cmdline-tools/latest" \
    && rm -rf /tmp/android-tools /tmp/android-tools.zip \
    && yes | sdkmanager --licenses >/dev/null \
    && sdkmanager "platforms;android-35" "build-tools;35.0.0"

WORKDIR /build/nikowashere_src
COPY nikowashere_src/ ./
RUN chmod +x gradlew \
    && ./gradlew --no-daemon assembleDebug


FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS package-build

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY server/ ./server/
COPY nikowashere_pdf/ ./nikowashere_pdf/
COPY --from=android-build \
    /build/nikowashere_src/app/build/outputs/apk/debug/app-debug.apk \
    ./server/assets/apps/niko-was-here.apk

RUN uv run ./nikowashere_pdf/md2pdf.py \
    && uv run python -c "from server.main import build_custom_zip; build_custom_zip()"


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    LOG_MODE=compliant \
    DATABASE_PATH=/data/trekstore.sqlite3

WORKDIR /app
RUN useradd --system --uid 10001 --home-dir /app trekstore \
    && mkdir /data \
    && chown trekstore:trekstore /data

COPY --from=package-build /app/.venv ./.venv
COPY --from=package-build --chown=trekstore:trekstore /app/server ./server

USER trekstore
EXPOSE 8000
VOLUME ["/data"]

CMD ["python", "-m", "server.main"]
