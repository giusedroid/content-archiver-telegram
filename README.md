# Content Archiver Telegram

This repository is the Telegram ingress for the content archive. It is intentionally thin:

1. authenticate Telegram users
2. download Telegram files
3. write an incoming request into the content repository
4. run the content repository MCP tools deterministically through a stdio MCP client
5. write MCP preprocessing results back into the incoming request
6. select the correct Kiro workflow prompt by media type
7. invoke Kiro headless with the content repository as the working directory
8. commit successful capture changes
9. optionally push directly or open a pull request
10. return Kiro's concise result to Telegram

The content repository owns the `.kiro` steering, workflow prompts, MCP tool definitions,
MCP implementation, captures, TODOs, and index files. This repo does not decide capture
semantics and does not own archive-scoped tools. This repo temporarily acts as an MCP
client because `kiro-cli chat` currently reads MCP configuration but does not surface
configured MCP tools as callable tools in non-interactive sessions.

## Architecture

```text
Telegram
  |
  v
content-archiver-telegram
  |  owns Telegram auth, downloads, request lifecycle, Docker runtime
  |  writes .content-archiver/incoming/<request-id>/request.yml
  v
content-archive-repo checkout
  |
  |<-- stdio MCP: uv run --project tools content-archive-mcp
  |    tools live in content-archive-repo/tools/
  |
  v
enriched request.yml
  |  includes preprocessing.steps with S3 URIs, previews, transcripts,
  |  crawled markdown, extracted frames/audio, or tool failures
  v
Kiro headless
  |  reads .kiro/workflows/<media-workflow>.md
  |  reads enriched request.yml
  |  classifies and edits captures/, todo/, index/
  v
git commit / optional push or pull request
  |
  v
Telegram reply
```

Current default mode:

```env
ARCHIVE_MCP_PREPROCESS=true
KIRO_REQUIRE_MCP_STARTUP=false
```

The archive MCP tools still use the MCP protocol. The difference is who starts and calls
them: today the Telegram runtime is the MCP client; later Kiro can become the MCP client
again if `kiro-cli chat` reliably surfaces configured MCP tools.

This is intentionally unorthodox. It exists because Kiro CLI currently has a runtime
issue where configured MCP servers may not be loaded or surfaced as callable tools in the
default CLI chat runtime. See
[kirodotdev/Kiro#7425](https://github.com/kirodotdev/Kiro/issues/7425), where `/mcp`
shows zero servers in the default CLI mode while the same MCP servers work in
`--classic`. Until that Kiro-side MCP lifecycle is reliable, this repo runs the archive
MCP lifecycle directly and passes the results to Kiro through `request.yml`.

## Boundaries And Contract

There are two repositories with separate responsibilities.

```text
content-archiver-telegram
  Owns:
    - Telegram bot commands and message handlers
    - Telegram user allowlist/security
    - Telegram file download cache
    - Docker image and startup sequence
    - Cloning/updating the content repo runtime checkout
    - Per-request git worktrees and branches in pull-request mode
    - Stdio MCP client used for deterministic preprocessing
    - Kiro process invocation
    - Git commit, push, and GitHub PR creation

content-archive-repo
  Owns:
    - Archive workspace layout
    - .kiro steering and workflow prompts
    - .kiro/settings/mcp.json
    - MCP server implementation under tools/
    - MCP tool dependency lockfile
    - captures/, todo/, index/
    - The durable markdown/YAML/previews/transcripts output model
```

The contract between the repos is file-based plus MCP-based:

```text
1. content-archiver-telegram writes:
   .content-archiver/incoming/<request-id>/request.yml

2. content-archiver-telegram calls the content repo MCP server:
   uv run --project tools content-archive-mcp

3. content-archiver-telegram updates request.yml with:
   preprocessing:
     enabled: true
     status: completed
     steps:
       - tool: upload_original_to_s3
         arguments: ...
         result: ...

4. Kiro reads the enriched request.yml and content repo context.

5. Kiro writes archive outputs:
   captures/<capture-id>/
   todo/
   index/

6. content-archiver-telegram commits and optionally pushes/opens a PR.
```

`request.yml` is the handoff document. Kiro should treat `preprocessing.steps` as the
source of truth for deterministic tool results and should not try to call MCP tools,
shell commands, or subagents as a fallback in non-interactive mode.

The MCP server/tool contract belongs to `content-archive-repo`, not this repo. The
Telegram runtime calls that contract but does not reimplement archive tool behavior.

## Setup

```bash
uv sync --group dev
cp .env.example .env
```

On Windows PowerShell:

```powershell
uv sync --group dev
Copy-Item .env.example .env
```

Configure:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=123456789
CONTENT_REPO_PATH=../content-archive-repo
KIRO_CLI=kiro-cli
KIRO_API_KEY=
```

Run:

```bash
uv run content-archiver-telegram serve
```

Process a local file through the same Kiro handoff path:

```bash
uv run content-archiver-telegram process-file ./photo.jpg --caption "AWS London Summit"
```

Run semantic search through Kiro:

```bash
uv run content-archiver-telegram search "Jeff Barr AWS London Summit"
```

## Run With Docker

The Docker image follows the same headless Kiro pattern as `simple-kirolets`: it installs
the Telegram ingress, installs `kiro-cli`, runs Telegram polling as one process, and lets
Kiro operate inside a content repository checkout stored in a Docker named volume.

The archive repo owns the MCP tool code and dependency graph under `tools/`. At container
startup, the Telegram entrypoint runs:

```bash
uv sync --project "$CONTENT_REPO_PATH/tools" --locked --no-dev
```

That installs the cloned archive tools into their own uv-managed environment before the
bot starts. The Docker image supplies the compute basics (`uv`, Python, Git, ffmpeg, Kiro
CLI); the archive repo supplies the tool project and lockfile.

Build and start:

```bash
cp .env.example .env
docker compose up --build
```

Default compose uses:

```text
content-repo volume -> /workspace/content-repo
./.docker/aws-empty -> /root/.aws
telegram-downloads volume -> /app/.content-archiver-telegram
```

On startup, `CONTENT_REPO_MODE=clone` clones or updates `CONTENT_REPO_GIT_URL` inside the
`content-repo` volume. This avoids running Kiro, `uv`, and MCP imports over a Windows bind
mount. GitHub is the source of truth for the runtime archive checkout; push archive repo
infrastructure changes before expecting the bot to use them.

For AWS profile credentials, set `AWS_PROFILE` and point `AWS_CONFIG_HOST_PATH` at your
host AWS config directory:

```env
AWS_PROFILE=your-profile
AWS_CONFIG_HOST_PATH=C:/Users/Admin/.aws
```

On macOS/Linux that path usually looks like:

```env
AWS_CONFIG_HOST_PATH=/home/giuseppe/.aws
```

The container sets:

```env
CONTENT_REPO_MODE=clone
CONTENT_REPO_GIT_URL=https://github.com/giusedroid/content-archive-repo.git
CONTENT_REPO_PATH=/workspace/content-repo
KIRO_CLI=kiro-cli
TELEGRAM_DOWNLOAD_DIR=/app/.content-archiver-telegram/downloads
KIRO_TRUST_TOOLS=read,grep,write,@content-archiver-tools/crawl_url_to_markdown,@content-archiver-tools/extract_audio,@content-archiver-tools/extract_video_frames,@content-archiver-tools/index_lancedb,@content-archiver-tools/pdf_to_markdown,@content-archiver-tools/resize_image,@content-archiver-tools/semantic_search,@content-archiver-tools/transcribe_audio,@content-archiver-tools/upload_original_to_s3
KIRO_REQUIRE_MCP_STARTUP=true
ARCHIVE_TOOLS_SYNC=true
ARCHIVE_TOOLS_SYNC_ARGS=--locked --no-dev
```

Only run one polling process for a Telegram bot token at a time.

## Delivery Modes

Kiro is responsible for editing files. After Kiro returns valid JSON, the Telegram runtime
stages and commits the changed files.

Direct commit mode is the default:

```env
CAPTURE_DELIVERY_MODE=commit
```

In direct commit mode, the runtime content repo worktree must be clean before accepting a
new capture. This prevents a later successful capture from accidentally committing older
partial output. Direct mode can also push deterministically when enabled:

```env
GIT_PUSH=true
GIT_REMOTE=origin
GIT_BRANCH=main
GITHUB_USERNAME=giusedroid
GITHUB_TOKEN=<github-pat>
```

Pull request mode is the concurrency path:

```env
CAPTURE_DELIVERY_MODE=pull-request
GIT_WORKTREE_ROOT=/app/.content-archiver-telegram/worktrees
GIT_BRANCH_PREFIX=capture
GIT_REMOTE=origin
GIT_BRANCH=main
GITHUB_REPOSITORY=giusedroid/content-archive-repo
GITHUB_TOKEN=<github-pat>
```

In pull request mode, each request gets an isolated git worktree and branch:

```text
capture/<request-id>
```

The runtime runs Kiro inside that worktree, commits the result, pushes the request branch,
and opens a GitHub pull request. The PR body includes Kiro's redacted stdout/stderr log so
you can inspect exactly what the headless agent saw and did. That lets multiple Telegram
requests run without sharing one mutable checkout.

Use a fine-grained GitHub PAT scoped only to the content repository. For direct archive
pushes or pull-request mode, start with:

```text
Metadata: read
Contents: read/write
```

The runtime snapshots `HEAD` before Kiro runs. After Kiro returns valid JSON, it runs:

```text
git add -A
git commit -m "capture: add <capture-id> <media-type>"
```

If the commit changed and `GIT_PUSH=true`, it then runs:

```text
git -c http.https://github.com/.extraheader="AUTHORIZATION: Basic <token>" push <remote> HEAD:<branch>
```

The token is passed through a temporary Git config entry for that one command and is not
written into `.git/config`.

The bot also supports:

```text
/status <request-id>
```

In pull request mode, this looks up the request branch and returns the matching PR URL.

Run the archive repo MCP server manually from the content repo after syncing tools:

```bash
cd ../content-archive-repo
uv sync --project tools --group dev
tools/.venv/bin/content-archive-mcp --check
```

Kiro starts the content repo MCP launcher from `.kiro/settings/mcp.json`:

```text
uv run --project tools content-archive-mcp
```

That launcher and the tool implementation live in the content archive repo.
By default, the Telegram runtime invokes Kiro with `--require-mcp-startup` so broken or
missing MCP tools fail loudly instead of producing partial capture notes.

## Workflow Selection

The Telegram interface maps media types to content-repo workflows:

```text
image -> .kiro/workflows/capture-image.md
video -> .kiro/workflows/capture-video.md
audio/voice -> .kiro/workflows/capture-audio.md
pdf -> .kiro/workflows/capture-pdf.md
link -> .kiro/workflows/capture-link.md
text -> .kiro/workflows/capture-text.md
search -> direct MCP calls: index_lancedb, semantic_search
```

For capture workflows, the Telegram runtime executes deterministic archive MCP tools first
and writes their results into the intake file. Kiro then reads the workflow prompt and
enriched request, edits files directly, and returns JSON with a Telegram-friendly message.
The Telegram runtime creates the commit after a successful Kiro result.

`/search` intentionally bypasses Kiro while Kiro CLI MCP startup is unreliable. The Telegram
runtime starts the archive MCP server itself, refreshes the semantic index, and calls
`semantic_search` directly.

## MCP Tool Runtime

The archive repo MCP server exposes:

```text
upload_original_to_s3
resize_image
extract_video_frames
extract_audio
transcribe_audio
pdf_to_markdown
crawl_url_to_markdown
index_lancedb
semantic_search
```

The tools are for external/heavy capabilities only. Kiro should use normal repository
access for reading/writing files and Git operations. This Telegram repo supplies the Docker
compute environment and startup sync; the archive repo supplies the MCP code and Python
dependency lockfile.

## Semantic Search

Run a one-off index refresh:

```bash
content-archiver-telegram index
```

Search from the CLI:

```bash
content-archiver-telegram search "Jeff Barr AWS London Summit"
```

Inside Docker debug shells the CLI is also symlinked into `/usr/local/bin`, so this works
with `docker compose exec telegram-bot ...` after rebuilding the image.

Search from Telegram:

```text
/search Jeff Barr AWS London Summit
```

Search results are grouped by capture instead of raw chunks. Each result includes a short
snippet, an `Open capture` GitHub URL, and an `Open matched file` GitHub URL with line
anchors when the archive index has line metadata. Links are built from
`GITHUB_REPOSITORY` and `GIT_BRANCH`, so `GITHUB_REPOSITORY` should point at the content
archive repo, not this Telegram runtime repo.

For NVIDIA Build/NIM embeddings:

```env
EMBEDDING_PROVIDER=nvidia
EMBEDDING_MODEL=nvidia/nv-embed-v1
NVIDIA_API_KEY=<your NVIDIA API key>
```

The archive MCP tools use NVIDIA `input_type=passage` while indexing and `input_type=query`
while searching.
