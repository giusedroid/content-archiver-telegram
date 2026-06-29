# Telegram Interface Spec

## Purpose

This repository provides the Telegram surface for a Kiro-operated content archive. It is not the semantic orchestrator. It is an ingress adapter and Kiro workflow launcher.

## Responsibilities

- Authenticate Telegram users with an allowlist.
- Download Telegram files into a local runtime cache.
- Refuse new captures when the content repository has pre-existing uncommitted changes.
- Copy or move incoming files into the content repository under `.content-archiver/incoming/<request-id>/`.
- Write a durable `request.yml` describing the incoming item.
- Select a workflow prompt from the content repository `.kiro/workflows/` directory based on media type.
- Invoke Kiro headless with the content repository as `cwd`.
- Commit successful capture changes in the content repository after Kiro returns valid JSON.
- Optionally push the new commit to the configured remote.
- Relay Kiro's result back to Telegram.
- Provide `/search` as a Kiro-mediated semantic search capability.

## Non-Responsibilities

- Capture boundary classification.
- Manifest semantics.
- Owning archive MCP tool implementation.
- Direct semantic editing of `captures/`, `todo/`, or `index/`.

Those are owned by Kiro operating inside the content repository and by the content repository MCP tools.

The archive repository owns both the durable MCP definitions and the archive-scoped MCP
tool implementation under its root `tools/` directory. This Telegram repo is only a
compute host that can run those tools.

## Incoming Request Format

Each incoming request is written as:

```text
.content-archiver/incoming/<request-id>/request.yml
```

Example:

```yaml
id: 2026-06-29-telegram-123456
source: telegram
media_type: video
caption: "me interviewing Jeff Barr at the London AWS summit"
text: null
local_original_path: .content-archiver/incoming/2026-06-29-telegram-123456/original.mp4
source_message_id: "123456"
received_at: 2026-06-29T10:42:00Z
telegram:
  user_id: 123456789
  chat_id: 987654321
  file_name: original.mp4
```

## Workflow Mapping

```text
image -> .kiro/workflows/capture-image.md
video -> .kiro/workflows/capture-video.md
voice -> .kiro/workflows/capture-audio.md
audio -> .kiro/workflows/capture-audio.md
pdf -> .kiro/workflows/capture-pdf.md
link -> .kiro/workflows/capture-link.md
text -> .kiro/workflows/capture-text.md
search -> .kiro/workflows/search.md
```

## Kiro Invocation

The interface invokes Kiro as:

```text
kiro-cli chat --no-interactive --trust-tools=<KIRO_TRUST_TOOLS> --require-mcp-startup <prompt>
```

The prompt includes:

- workflow file path
- workflow text
- incoming request path
- expected JSON result shape

Kiro runs with `cwd` set to the content repository root so it behaves like Kiro IDE opened on that repo.
`KIRO_REQUIRE_MCP_STARTUP=true` is the default. If MCP startup fails, the Telegram
interface should fail the capture instead of allowing Kiro to write partial "MCP tools
unavailable" notes. The switch may be set to `false` only for deliberate local debugging.

## Docker Runtime

The Telegram interface must be runnable as a single portable Docker service.

The container image must:

- use `uv` to install the Python package from `pyproject.toml` and `uv.lock`
- install `kiro-cli` during the Docker build
- install Git and `ffmpeg`
- provide Python and `uv` so mounted archive repo tools can be synced at startup
- run `content-archiver-telegram serve` by default
- set `KIRO_CLI=kiro-cli`
- set `CONTENT_REPO_PATH=/workspace/content-repo`
- set `TELEGRAM_DOWNLOAD_DIR=/app/.content-archiver-telegram/downloads`
- configure the mounted content repository as a Git safe directory
- optionally configure Git author identity from `GIT_USER_NAME` and `GIT_USER_EMAIL`

Docker Compose must mount:

- the content repository into `/workspace/content-repo`
- a persistent Telegram download/cache volume into `/app/.content-archiver-telegram`
- an optional host AWS config directory into `/root/.aws` so `AWS_PROFILE` works

The default host content repo path is:

```text
../content-archive-repo
```

The default AWS config mount is an empty placeholder directory so local dry-run mode works
without host AWS credentials.

At startup, before the Telegram bot begins polling, the entrypoint must install the mounted
archive tools project:

```bash
uv sync --project "$CONTENT_REPO_PATH/tools" --locked --no-dev
```

This behavior is controlled by:

```env
ARCHIVE_TOOLS_SYNC=true
ARCHIVE_TOOLS_SYNC_ARGS=--locked --no-dev
```

The Docker image must not own or vendor archive MCP Python dependencies. The archive repo
owns `tools/pyproject.toml` and `tools/uv.lock`; the Telegram container only supplies the
compute environment that syncs and runs that project.

## Commit And Push Runtime

Kiro is responsible for editing files inside the content repository. The Telegram runtime
is responsible for creating the local commit after a valid capture result and for optional
remote push behavior.

Environment variables:

```env
GIT_PUSH=false
GIT_REMOTE=origin
GIT_BRANCH=main
GITHUB_USERNAME=giusedroid
GITHUB_TOKEN=
```

When `GIT_PUSH=true`, `GITHUB_TOKEN` is required. The expected token is a fine-grained
GitHub PAT scoped to the content repository with at least Metadata read and Contents
read/write.

Capture workflow push procedure:

1. Verify the content repository worktree is clean before writing the new incoming request.
2. Snapshot `HEAD` in the content repository before invoking Kiro.
3. Invoke Kiro with the content repository as `cwd`.
4. Parse Kiro's JSON response.
5. If the content repo has changes, run `git add -A` and `git commit -m "capture: add <capture-id> <media-type>"`.
6. If `HEAD` changed and `GIT_PUSH=true`, push `HEAD:<GIT_BRANCH>` to `<GIT_REMOTE>`.
7. Use a temporary Git HTTP auth header for the push command.
8. Do not write the GitHub token into `.git/config`.
9. Do not pass `GITHUB_TOKEN` into the Kiro subprocess environment.
10. Redact both raw tokens and temporary auth headers from runtime errors.

Search workflows must not commit or push.

## MCP Runtime

The content repo `.kiro/settings/mcp.json` should invoke its repo-local launcher over stdio:

```text
python tools/content_archiver_mcp.py
```

That launcher imports the archive repo's MCP runtime from `tools/content_archive_mcp/`.
Tools exposed by the server:

- `upload_original_to_s3`
- `resize_image`
- `extract_video_frames`
- `extract_audio`
- `transcribe_audio`
- `pdf_to_markdown`
- `crawl_url_to_markdown`
- `index_lancedb`
- `semantic_search`

## Expected Kiro Result

Kiro should return JSON:

```json
{
  "ok": true,
  "message": "Archived under captures/aws-london-summit-2026.",
  "capture_id": "aws-london-summit-2026",
  "paths": [
    "captures/aws-london-summit-2026/manifest.yml"
  ]
}
```

The Telegram interface should fall back to a concise failure message if Kiro fails or returns invalid JSON.
