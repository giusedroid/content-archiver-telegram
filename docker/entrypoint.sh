#!/usr/bin/env bash
set -euo pipefail

: "${CONTENT_REPO_PATH:=/workspace/content-repo}"
: "${TELEGRAM_DOWNLOAD_DIR:=/app/.content-archiver-telegram/downloads}"
: "${CONTENT_REPO_MODE:=clone}"
: "${CONTENT_REPO_GIT_URL:=}"
: "${ARCHIVE_TOOLS_SYNC:=true}"
: "${ARCHIVE_TOOLS_SYNC_ARGS:=--locked --no-dev}"

mkdir -p "$TELEGRAM_DOWNLOAD_DIR"

git_auth_args=()
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  auth_payload="$(printf '%s:%s' "${GITHUB_USERNAME:-x-access-token}" "$GITHUB_TOKEN" | base64 | tr -d '\n')"
  git_auth_args=(-c "http.https://github.com/.extraheader=AUTHORIZATION: Basic $auth_payload")
fi

run_git() {
  git "${git_auth_args[@]}" "$@"
}

prepare_cloned_content_repo() {
  if [[ -z "$CONTENT_REPO_GIT_URL" ]]; then
    echo "CONTENT_REPO_GIT_URL is required when CONTENT_REPO_MODE=clone." >&2
    exit 1
  fi

  mkdir -p "$(dirname "$CONTENT_REPO_PATH")"

  if [[ ! -d "$CONTENT_REPO_PATH/.git" ]]; then
    if [[ -d "$CONTENT_REPO_PATH" ]] && [[ -n "$(find "$CONTENT_REPO_PATH" -mindepth 1 -maxdepth 1 2>/dev/null)" ]]; then
      echo "$CONTENT_REPO_PATH is not empty and is not a git checkout." >&2
      exit 1
    fi
    run_git clone --branch "${GIT_BRANCH:-main}" "$CONTENT_REPO_GIT_URL" "$CONTENT_REPO_PATH"
  fi

  if [[ -n "$(git -C "$CONTENT_REPO_PATH" status --porcelain)" ]]; then
    echo "Content repository has uncommitted changes; refusing startup sync." >&2
    exit 1
  fi

  run_git -C "$CONTENT_REPO_PATH" fetch "${GIT_REMOTE:-origin}" "${GIT_BRANCH:-main}"
  git -C "$CONTENT_REPO_PATH" checkout "${GIT_BRANCH:-main}"
  git -C "$CONTENT_REPO_PATH" reset --hard "${GIT_REMOTE:-origin}/${GIT_BRANCH:-main}"
}

if command -v git >/dev/null 2>&1; then
  if [[ "$CONTENT_REPO_MODE" == "clone" ]]; then
    prepare_cloned_content_repo
  elif [[ "$CONTENT_REPO_MODE" != "bind" ]]; then
    echo "CONTENT_REPO_MODE must be 'clone' or 'bind'." >&2
    exit 1
  fi

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

export PATH="$CONTENT_REPO_PATH/tools/.venv/bin:$PATH"

exec "$@"
