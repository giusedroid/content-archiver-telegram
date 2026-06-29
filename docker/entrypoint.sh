#!/usr/bin/env bash
set -euo pipefail

: "${CONTENT_REPO_PATH:=/workspace/content-repo}"
: "${TELEGRAM_DOWNLOAD_DIR:=/app/.content-archiver-telegram/downloads}"

mkdir -p "$TELEGRAM_DOWNLOAD_DIR"

if command -v git >/dev/null 2>&1; then
  git config --global --add safe.directory "$CONTENT_REPO_PATH" || true

  if [[ -n "${GIT_USER_NAME:-}" ]]; then
    git config --global user.name "$GIT_USER_NAME"
  fi

  if [[ -n "${GIT_USER_EMAIL:-}" ]]; then
    git config --global user.email "$GIT_USER_EMAIL"
  fi
fi

exec "$@"
