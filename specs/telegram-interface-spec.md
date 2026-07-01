# Telegram Interface Spec

## Purpose

This repository provides the Telegram surface for a Kiro-operated content archive. It is not the semantic orchestrator. It is an ingress adapter, deterministic archive MCP client, and Kiro workflow launcher.

## Responsibilities

- Authenticate Telegram users with an allowlist.
- Download Telegram files into a local runtime cache.
- Refuse new direct-mode captures when the content repository has pre-existing uncommitted changes.
- In pull-request mode, create an isolated git worktree and request branch per capture.
- Copy or move incoming files into the content repository under `.content-archiver/incoming/<request-id>/`.
- Write a durable `request.yml` describing the incoming item.
- Select a workflow prompt from the content repository `.kiro/workflows/` directory based on media type.
- Invoke Kiro headless with the content repository as `cwd`.
- Commit successful capture changes in the content repository after Kiro returns valid JSON.
- Optionally push directly or push a request branch and open a GitHub pull request.
- Relay Kiro's result back to Telegram.
- Provide `/search` through direct archive MCP calls to `index_lancedb` and `semantic_search`.
- Provide `/status <request-id>` to look up request pull requests.

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
search -> direct MCP calls: index_lancedb, semantic_search
```

## Kiro Invocation

The interface invokes Kiro as:

```text
kiro-cli chat --no-interactive --trust-tools=<KIRO_TRUST_TOOLS> --require-mcp-startup <prompt>
```

`KIRO_TRUST_TOOLS` includes Kiro's filesystem tools and archive MCP tool names prefixed
with the MCP server name for forward compatibility. While Kiro CLI MCP startup is
unreliable, capture preprocessing and search call the archive MCP server directly from the
Telegram runtime. The default is:

```text
read,grep,write,@content-archiver-tools/crawl_url_to_markdown,@content-archiver-tools/extract_audio,@content-archiver-tools/extract_video_frames,@content-archiver-tools/index_lancedb,@content-archiver-tools/pdf_to_markdown,@content-archiver-tools/resize_image,@content-archiver-tools/semantic_search,@content-archiver-tools/transcribe_audio,@content-archiver-tools/upload_original_to_s3
```

The runtime should normalize older bare archive tool names such as `resize_image` to
`@content-archiver-tools/resize_image`.

The prompt includes:

- workflow file path
- workflow text
- incoming request path
- expected JSON result shape

Kiro runs with `cwd` set to the content repository root so it behaves like Kiro IDE opened on that repo.
Kiro should read the enriched request file and edit archive files directly; it should not
re-run deterministic MCP preprocessing.
`KIRO_REQUIRE_MCP_STARTUP=false` is the default while Kiro CLI MCP startup is unreliable.
The Telegram runtime executes archive MCP preprocessing itself before invoking Kiro.
If `KIRO_REQUIRE_MCP_STARTUP=true`, the Telegram interface should fail the capture when MCP
startup fails instead of allowing Kiro to write partial "MCP tools unavailable" notes.
Because Kiro CLI can currently emit MCP startup failures as warnings while still exiting
with status 0, the Telegram runtime must scan Kiro stdout/stderr for `Failed to retrieve
MCP settings` and `MCP functionality disabled` and treat either as a failed run before
committing or opening a pull request.

Kiro diagnostics are controlled by:

```env
KIRO_VERBOSE=0
KIRO_LOG_DIR=.content-archiver-telegram/kiro-logs
LOG_LEVEL=INFO
```

`KIRO_VERBOSE` maps to repeated Kiro CLI `-v` flags. For example, `KIRO_VERBOSE=2`
invokes `kiro-cli chat -v -v ...`. The runtime must log a redacted Kiro transcript for
each run under `KIRO_LOG_DIR`, including cwd, command shape, return code, stdout, and
stderr. Runtime logs must include the redacted transcript path when a Kiro/MCP failure is
detected.

## Search

Search is intentionally not routed through Kiro while Kiro CLI MCP startup is unreliable.

Flow:

1. User sends `/search <query>`.
2. Telegram runtime starts the content repo MCP server over stdio.
3. Telegram runtime calls `index_lancedb` to refresh changed markdown.
4. Telegram runtime calls `semantic_search`.
5. Telegram groups matching chunks by capture and returns concise results.

Search results should include:

- capture title derived from `capture_id`
- best matched file path
- short text snippet
- `Open capture` GitHub URL
- `Open matched file` GitHub URL, with line anchors when available

Links are built from `GITHUB_REPOSITORY` and `GIT_BRANCH`; `GITHUB_REPOSITORY` must refer
to the content archive repository.

`/search` may refresh generated index files in the runtime archive checkout. Those files
must be treated as runtime artifacts, not capture changes. The Telegram runtime should
remove or restore `index/lancedb-manifest.yml`, `index/index-report.json`, and
`index/semantic-records.jsonl` after search and before startup sync so generated index
state cannot block later captures or container restarts.

For NVIDIA Build/NIM embeddings:

```env
EMBEDDING_PROVIDER=nvidia
EMBEDDING_MODEL=nvidia/nv-embed-v1
NVIDIA_API_KEY=
```

The archive MCP tool uses NVIDIA `input_type=passage` for index chunks and
`input_type=query` for user search queries.

## Docker Runtime

The Telegram interface must be runnable as a single portable Docker service.

The container image must:

- use `uv` to install the Python package from `pyproject.toml` and `uv.lock`
- install `kiro-cli` during the Docker build
- expose `kiro-cli` through a stable `/usr/local/bin/kiro-cli` symlink
- install Git and `ffmpeg`
- provide Python and `uv` so cloned archive repo tools can be synced at startup
- run `content-archiver-telegram serve` by default
- set `KIRO_CLI=/usr/local/bin/kiro-cli`
- set `CONTENT_REPO_PATH=/workspace/content-repo`
- set `TELEGRAM_DOWNLOAD_DIR=/app/.content-archiver-telegram/downloads`
- configure the cloned content repository as a Git safe directory
- optionally configure Git author identity from `GIT_USER_NAME` and `GIT_USER_EMAIL`

Docker Compose must mount:

- a Docker named volume for the content repository at `/workspace/content-repo`
- a persistent Telegram download/cache volume into `/app/.content-archiver-telegram`
- an optional host AWS config directory into `/root/.aws` so `AWS_PROFILE` works

The default content repo mode is:

```env
CONTENT_REPO_MODE=clone
CONTENT_REPO_GIT_URL=https://github.com/giusedroid/content-archive-repo.git
```

At startup, clone mode should clone the content repository into the named Docker volume if
it is absent. If it already exists, the entrypoint should refuse to continue when the
checkout is dirty, then fetch and reset the configured branch to the remote branch.
Authentication must use a temporary Git HTTP auth header derived from `GITHUB_TOKEN`, not
a token persisted in `.git/config`.

The default AWS config mount is an empty placeholder directory so local dry-run mode works
without host AWS credentials.

At startup, before the Telegram bot begins polling, the entrypoint must install the cloned
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

In pull-request mode, request worktrees must reuse the already-synced archive tools
environment from the main runtime checkout. After creating a request worktree, the
Telegram runtime links:

```text
<request-worktree>/tools/.venv -> /workspace/content-repo/tools/.venv
```

This prevents Kiro/MCP startup from installing archive tool dependencies separately for
every request branch.

The active MCP registration should remain portable for Kiro IDE and Docker. It may use
`uv run --project tools content-archive-mcp`; Docker performance comes from cloning the
archive into a Linux-native volume and disabling runtime bytecode compilation, not from a
container-only command path.

As a compatibility workaround for Kiro CLI MCP discovery, the Docker entrypoint also
mirrors the archive repo MCP config into Kiro's global settings path before starting the
bot:

```text
/workspace/content-repo/.kiro/settings/mcp.json -> /root/.kiro/settings/mcp.json
```

This behavior is controlled by:

```env
KIRO_GLOBAL_MCP_SYNC=true
KIRO_GLOBAL_MCP_PATH=/root/.kiro/settings/mcp.json
```

The archive repository remains the source of truth. The global file is a runtime copy
used only so Kiro CLI can try global MCP discovery.

## Delivery Runtime

Kiro is responsible for editing files inside the content repository. The Telegram runtime
is responsible for creating the local commit after a valid capture result. Delivery is
controlled by `CAPTURE_DELIVERY_MODE`.

Environment variables:

```env
CAPTURE_DELIVERY_MODE=commit
GIT_PUSH=false
GIT_REMOTE=origin
GIT_BRANCH=main
GIT_WORKTREE_ROOT=.content-archiver-telegram/worktrees
GIT_BRANCH_PREFIX=capture
GITHUB_USERNAME=giusedroid
GITHUB_TOKEN=
GITHUB_REPOSITORY=
```

Supported modes:

- `commit`: use the runtime content repo checkout directly.
- `pull-request`: create a per-request git worktree, branch, commit, push, and GitHub PR.

When `GIT_PUSH=true` or `CAPTURE_DELIVERY_MODE=pull-request`, `GITHUB_TOKEN` is required.
The expected token is a fine-grained GitHub PAT scoped to the content repository with at
least Metadata read and Contents read/write.

Direct commit procedure:

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

Pull request procedure:

1. Create branch `capture/<request-id>` from `GIT_BRANCH`.
2. Create a git worktree under `GIT_WORKTREE_ROOT/<request-id>`.
3. Link the request worktree `tools/.venv` to the main runtime checkout `tools/.venv`.
4. Write `.content-archiver/incoming/<request-id>/request.yml` inside that worktree.
5. Invoke Kiro with the request worktree as `cwd`.
6. Commit changed files in that worktree.
7. Push `HEAD:refs/heads/capture/<request-id>` to `GIT_REMOTE`.
8. Open a pull request from `capture/<request-id>` into `GIT_BRANCH`.
9. Include the full redacted Kiro stdout/stderr log in the pull request body.
10. Reply to Telegram with the request id, Kiro summary, proposed location, and PR URL.

Search workflows must not commit or push.

## MCP Runtime

The content repo `.kiro/settings/mcp.json` should invoke its repo-local launcher over stdio:

```text
uv run --project tools content-archive-mcp
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
