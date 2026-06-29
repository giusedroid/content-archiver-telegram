# Content Archiver Telegram

This repository is the Telegram ingress for the content archive. It is intentionally thin:

1. authenticate Telegram users
2. download Telegram files
3. write an incoming request into the content repository
4. select the correct Kiro workflow prompt by media type
5. invoke Kiro headless with the content repository as the working directory
6. return Kiro's concise result to Telegram

The content repository owns the `.kiro` steering, workflow prompts, MCP tool definitions, captures, TODOs, and index files. This repo does not decide capture semantics.

This repository also provides the runtime executable named by the content repo MCP definition:

```text
content-archiver-mcp
```

The MCP definitions remain in the content repo so humans and agents can inspect the tool contract from the workspace. This package only supplies the implementation.

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

Run the MCP server manually:

```bash
uv run content-archiver-mcp
```

Kiro normally starts this command from the content repo using `.kiro/mcp/servers.yml`.

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

`content-archiver-mcp` exposes:

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

The tools are for external/heavy capabilities only. Kiro should use normal repository access for reading/writing files and Git operations.
