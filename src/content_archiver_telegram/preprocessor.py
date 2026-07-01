from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from .config import Settings
from .mcp_client import MCPClientError, StdioMCPClient


LOGGER = logging.getLogger(__name__)


class PreprocessError(RuntimeError):
    pass


def preprocess_request(settings: Settings, request_path: Path) -> dict[str, Any]:
    if not settings.archive_mcp_preprocess:
        return {"enabled": False, "status": "skipped", "steps": []}

    data = yaml.safe_load(request_path.read_text(encoding="utf-8")) or {}
    media_type = str(data.get("media_type") or "")
    request_id = str(data.get("id") or request_path.parent.name)
    LOGGER.info("Starting archive MCP preprocessing request=%s media_type=%s", request_id, media_type)
    try:
        with StdioMCPClient(settings) as client:
            result = _preprocess_with_client(client, settings, request_path, data)
    except MCPClientError as exc:
        raise PreprocessError(f"Archive MCP preprocessing failed: {exc}") from exc

    data["preprocessing"] = result
    request_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    LOGGER.info(
        "Finished archive MCP preprocessing request=%s steps=%s",
        request_id,
        len(result.get("steps", [])),
    )
    return result


def _preprocess_with_client(
    client: StdioMCPClient,
    settings: Settings,
    request_path: Path,
    data: dict[str, Any],
) -> dict[str, Any]:
    media_type = str(data.get("media_type") or "")
    request_id = str(data.get("id") or request_path.parent.name)
    original = data.get("local_original_path")
    filename = Path(str(original or request_id)).name
    steps: list[dict[str, Any]] = []

    def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        output = client.call_tool(name, arguments)
        steps.append({"tool": name, "arguments": arguments, "result": output})
        return output

    if media_type == "image" and original:
        call(
            "upload_original_to_s3",
            _upload_args(original, request_id, "image-original", filename),
        )
        call(
            "resize_image",
            {
                "input_path": original,
                "output_path": f".content-archiver/incoming/{request_id}/previews/image.jpg",
                "max_width": 1280,
            },
        )

    elif media_type in {"voice", "audio"} and original:
        call(
            "upload_original_to_s3",
            _upload_args(original, request_id, f"{media_type}-original", filename),
        )
        transcript = call("transcribe_audio", {"audio_path": original})
        _write_transcript(settings, request_id, transcript.get("transcript", ""))
        steps.append(
            {
                "tool": "write_transcript",
                "result": {
                    "transcript_path": f".content-archiver/incoming/{request_id}/transcripts/transcript.md"
                },
            }
        )

    elif media_type == "video" and original:
        call(
            "upload_original_to_s3",
            _upload_args(original, request_id, "video-original", filename),
        )
        call(
            "extract_video_frames",
            {
                "video_path": original,
                "output_dir": f".content-archiver/incoming/{request_id}/previews/video",
                "count": 2,
            },
        )
        audio = call(
            "extract_audio",
            {
                "video_path": original,
                "output_path": f".content-archiver/incoming/{request_id}/derived/audio.wav",
            },
        )
        transcript = call("transcribe_audio", {"audio_path": audio["audio_path"]})
        _write_transcript(settings, request_id, transcript.get("transcript", ""))
        steps.append(
            {
                "tool": "write_transcript",
                "result": {
                    "transcript_path": f".content-archiver/incoming/{request_id}/transcripts/transcript.md"
                },
            }
        )

    elif media_type == "pdf" and original:
        call(
            "upload_original_to_s3",
            _upload_args(original, request_id, "pdf-original", filename),
        )
        call(
            "pdf_to_markdown",
            {
                "pdf_path": original,
                "output_path": f".content-archiver/incoming/{request_id}/documents/document.md",
            },
        )

    elif media_type == "link":
        url = _first_url(str(data.get("text") or data.get("caption") or ""))
        if url:
            call(
                "crawl_url_to_markdown",
                {
                    "url": url,
                    "output_path": f".content-archiver/incoming/{request_id}/links/source.md",
                },
            )

    return {"enabled": True, "status": "completed", "steps": steps}


def _upload_args(original: str, request_id: str, asset_id: str, filename: str) -> dict[str, str]:
    return {
        "local_path": original,
        "capture_id": "_intake",
        "asset_id": f"{request_id}-{asset_id}",
        "original_filename": filename,
    }


def _write_transcript(settings: Settings, request_id: str, transcript: str) -> None:
    target = (
        settings.content_repo_path
        / ".content-archiver"
        / "incoming"
        / request_id
        / "transcripts"
        / "transcript.md"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    content = (transcript or "# Transcript\n\nNo transcript returned.").rstrip() + "\n"
    target.write_text(content, encoding="utf-8")


def _first_url(text: str) -> str | None:
    match = re.search(r"https?://\S+", text)
    return match.group(0).rstrip(").,]") if match else None
