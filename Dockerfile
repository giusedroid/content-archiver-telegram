FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    CONTENT_REPO_PATH=/workspace/content-repo \
    TELEGRAM_DOWNLOAD_DIR=/app/.content-archiver-telegram/downloads \
    KIRO_CLI=/usr/local/bin/kiro-cli \
    PATH="/root/.local/bin:/root/.kiro/bin:/app/.venv/bin:${PATH}"

WORKDIR /app

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://cli.kiro.dev/install | bash \
    && KIRO_CLI_BIN="$(command -v kiro-cli)" \
    && ln -sf "$KIRO_CLI_BIN" /usr/local/bin/kiro-cli \
    && /usr/local/bin/kiro-cli --version

COPY pyproject.toml uv.lock .python-version README.md ./
COPY src ./src
COPY docker/entrypoint.sh /usr/local/bin/content-archiver-entrypoint

RUN uv sync --locked --no-dev \
    && ln -sf /app/.venv/bin/content-archiver-telegram /usr/local/bin/content-archiver-telegram \
    && chmod +x /usr/local/bin/content-archiver-entrypoint

ENTRYPOINT ["content-archiver-entrypoint"]
CMD ["content-archiver-telegram", "serve"]
