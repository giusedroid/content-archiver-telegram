# Content Archiver Telegram

This repository is the Telegram ingress for the content archive. It is intentionally thin:

1. authenticate Telegram users
2. download Telegram files
3. write an incoming request into the content repository
4. select the correct Kiro workflow prompt by media type
5. invoke Kiro headless with the content repository as the working directory
6. return Kiro's concise result to Telegram

The content repository owns the `.kiro` steering, workflow prompts, MCP tool definitions,
MCP implementation, captures, TODOs, and index files. This repo does not decide capture
semantics and does not own archive-scoped tools.

## Architecture

```text
Telegram
  -> content-archiver-telegram
  -> content repo .content-archiver/incoming/<request-id>/request.yml
  -> Kiro headless in the content repo
  -> .kiro/workflows/<media-workflow>.md
  -> content-repo MCP tools for AWS/media/transcription/search
  -> captures/, todo/, index/
  -> Telegram reply
```

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
Python dependencies through `uv`, installs `kiro-cli`, runs Telegram polling as one
process, and lets Kiro operate inside a mounted content repository.

The archive repo owns the MCP tool code under `tools/`, but this Docker image installs the
dependencies needed to run those tools: `mcp`, `boto3`, `Pillow`, `ffmpeg`, `markitdown`,
`lancedb`, OpenAI-compatible clients, and related support libraries. The mounted archive
repo should not have to run `uv sync` inside the container for normal bot operation.

Build and start:

```bash
cp .env.example .env
docker compose up --build
```

Default compose mounts:

```text
../content-archive-repo -> /workspace/content-repo
./.docker/aws-empty -> /root/.aws
telegram-downloads volume -> /app/.content-archiver-telegram
```

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
CONTENT_REPO_PATH=/workspace/content-repo
KIRO_CLI=kiro-cli
TELEGRAM_DOWNLOAD_DIR=/app/.content-archiver-telegram/downloads
```

Only run one polling process for a Telegram bot token at a time.

## Git Push

Kiro is responsible for editing and committing inside the mounted content repo. The
Telegram runtime can push deterministically after Kiro succeeds:

```env
GIT_PUSH=true
GIT_REMOTE=origin
GIT_BRANCH=main
GITHUB_USERNAME=giusedroid
GITHUB_TOKEN=github_pat_xxxxx
```

Use a fine-grained GitHub PAT scoped only to the content repository. For direct archive
pushes, start with:

```text
Metadata: read
Contents: read/write
```

The runtime snapshots `HEAD` before Kiro runs. After Kiro returns valid JSON, it checks
`HEAD` again. If the commit changed and `GIT_PUSH=true`, it runs:

```text
git -c http.https://github.com/.extraheader="AUTHORIZATION: Basic <token>" push <remote> HEAD:<branch>
```

The token is passed through a temporary Git config entry for that one command and is not
written into `.git/config`.

Run the archive repo MCP server manually from the mounted content repo:

```bash
cd ../content-archive-repo
uv run content-archive-mcp --check
```

Kiro starts the content repo MCP launcher from `.kiro/settings/mcp.json`:

```text
python tools/content_archiver_mcp.py
```

That launcher and the tool implementation live in the mounted content archive repo.

## Workflow Selection

The Telegram interface maps media types to content-repo workflows:

```text
image -> .kiro/workflows/capture-image.md
video -> .kiro/workflows/capture-video.md
audio/voice -> .kiro/workflows/capture-audio.md
pdf -> .kiro/workflows/capture-pdf.md
link -> .kiro/workflows/capture-link.md
text -> .kiro/workflows/capture-text.md
search -> .kiro/workflows/search.md
```

Kiro is expected to read the workflow prompt, use the content repo MCP tools where needed, edit files directly, commit the result, and return JSON with a Telegram-friendly message.

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
compute environment and dependencies; the archive repo supplies the MCP code.
