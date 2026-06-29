# Telegram Interface Spec

## Purpose

This repository provides the Telegram surface for a Kiro-operated content archive. It is not the semantic orchestrator. It is an ingress adapter and Kiro workflow launcher.

## Responsibilities

- Authenticate Telegram users with an allowlist.
- Download Telegram files into a local runtime cache.
- Copy or move incoming files into the content repository under `.content-archiver/incoming/<request-id>/`.
- Write a durable `request.yml` describing the incoming item.
- Select a workflow prompt from the content repository `.kiro/workflows/` directory based on media type.
- Invoke Kiro headless with the content repository as `cwd`.
- Relay Kiro's result back to Telegram.
- Provide `/search` as a Kiro-mediated semantic search capability.

## Non-Responsibilities

- Capture boundary classification.
- Manifest semantics.
- S3 upload implementation.
- Media processing implementation.
- Transcription implementation.
- LanceDB indexing/search implementation.
- Direct editing of `captures/`, `todo/`, or `index/`.

Those are owned by Kiro operating inside the content repository and by the content repository MCP tools.

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
kiro-cli chat --no-interactive --trust-tools=<KIRO_TRUST_TOOLS> <prompt>
```

The prompt includes:

- workflow file path
- workflow text
- incoming request path
- expected JSON result shape

Kiro runs with `cwd` set to the content repository root so it behaves like Kiro IDE opened on that repo.

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
