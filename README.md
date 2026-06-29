# Content Archiver Telegram

This repository is the Telegram ingress for the content archive. It is intentionally thin:

1. authenticate Telegram users
2. download Telegram files
3. write an incoming request into the content repository
4. select the correct Kiro workflow prompt by media type
5. invoke Kiro headless with the content repository as the working directory
6. commit successful capture changes in the content repository
7. optionally push the new commit
8. return Kiro's concise result to Telegram

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
  -> git commit
  -> optional git push
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
the Telegram ingress, installs `kiro-cli`, runs Telegram polling as one process, and lets
Kiro operate inside a mounted content repository.

The archive repo owns the MCP tool code and dependency graph under `tools/`. At container
startup, the Telegram entrypoint runs:

```bash
uv sync --project "$CONTENT_REPO_PATH/tools" --locked --no-dev
```

That installs the mounted archive tools into their own uv-managed environment before the
bot starts. The Docker image supplies the compute basics (`uv`, Python, Git, ffmpeg, Kiro
CLI); the archive repo supplies the tool project and lockfile.

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
KIRO_REQUIRE_MCP_STARTUP=true
ARCHIVE_TOOLS_SYNC=true
ARCHIVE_TOOLS_SYNC_ARGS=--locked --no-dev
```

Only run one polling process for a Telegram bot token at a time.

## Commit And Push

Kiro is responsible for editing files inside the mounted content repo. After Kiro returns
valid JSON, the Telegram runtime stages and commits any content repo changes. It can also
push deterministically when enabled:

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

Run the archive repo MCP server manually from the mounted content repo:

```bash
cd ../content-archive-repo
uv run --project tools content-archive-mcp --check
```

Kiro starts the content repo MCP launcher from `.kiro/settings/mcp.json`:

```text
python tools/content_archiver_mcp.py
```

That launcher and the tool implementation live in the mounted content archive repo.
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
search -> .kiro/workflows/search.md
```

Kiro is expected to read the workflow prompt, use the content repo MCP tools where needed,
edit files directly, and return JSON with a Telegram-friendly message. The Telegram runtime
creates the commit after a successful Kiro result.

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
