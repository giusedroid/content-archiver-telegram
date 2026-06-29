#!/usr/bin/env bash
set -euo pipefail

: "${CONTENT_REPO_PATH:=/workspace/content-repo}"
: "${TELEGRAM_DOWNLOAD_DIR:=/app/.content-archiver-telegram/downloads}"
: "${ARCHIVE_TOOLS_SYNC:=true}"
: "${ARCHIVE_TOOLS_SYNC_ARGS:=--locked --no-dev}"

mkdir -p "$TELEGRAM_DOWNLOAD_DIR"

if command -v git >/dev/null 2>&1; then
  git config --global --add safe.directory "$CONTENT_REPO_PATH" || true
  git -C "$CONTENT_REPO_PATH" config core.autocrlf input || true
  git -C "$CONTENT_REPO_PATH" config core.filemode false || true

  if [[ -n "${GIT_USER_NAME:-}" ]]; then
    git config --global user.name "$GIT_USER_NAME"
  fi

  if [[ -n "${GIT_USER_EMAIL:-}" ]]; then
    git config --global user.email "$GIT_USER_EMAIL"
  fi
fi

if [[ "$ARCHIVE_TOOLS_SYNC" == "true" ]]; then
  if [[ ! -f "$CONTENT_REPO_PATH/tools/pyproject.toml" ]]; then
    echo "Archive tools project not found at $CONTENT_REPO_PATH/tools/pyproject.toml" >&2
    exit 1
  fi

  uv sync --project "$CONTENT_REPO_PATH/tools" $ARCHIVE_TOOLS_SYNC_ARGS
fi

exec "$@"
