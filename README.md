# Content Archiver Telegram

This repository is the Telegram ingress for the content archive. It is intentionally thin:

1. authenticate Telegram users
2. download Telegram files
3. write an incoming request into the content repository
4. select the correct Kiro workflow prompt by media type
5. invoke Kiro headless with the content repository as the working directory
6. return Kiro's concise result to Telegram

The content repository owns the `.kiro` steering, workflow prompts, MCP tool definitions, captures, TODOs, and index files. This repo does not decide capture semantics.

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
