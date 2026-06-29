from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class IncomingRequest:
    id: str
    media_type: str
    source: str = "telegram"
    caption: str | None = None
    text: str | None = None
    local_original_path: Path | None = None
    source_message_id: str | None = None
    received_at: str | None = None
    telegram: dict[str, Any] | None = None


def write_incoming_request(
    *,
    content_repo_path: Path,
    request: IncomingRequest,
    source_file: Path | None = None,
) -> Path:
    request_dir = content_repo_path / ".content-archiver" / "incoming" / request.id
    request_dir.mkdir(parents=True, exist_ok=True)

    original_rel: str | None = None
    if source_file is not None:
        target = request_dir / _safe_original_name(source_file.name, request.media_type)
        shutil.copy2(source_file, target)
        original_rel = target.relative_to(content_repo_path).as_posix()

    received_at = request.received_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    data: dict[str, Any] = {
        "id": request.id,
        "source": request.source,
        "media_type": request.media_type,
        "caption": request.caption,
        "text": request.text,
        "local_original_path": original_rel
        or (
            request.local_original_path.relative_to(content_repo_path).as_posix()
            if request.local_original_path and request.local_original_path.is_absolute()
            else str(request.local_original_path) if request.local_original_path else None
        ),
        "source_message_id": request.source_message_id,
        "received_at": received_at,
        "telegram": request.telegram or {},
    }
    request_path = request_dir / "request.yml"
    request_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return request_path


def request_id(*, source: str, message_id: str | None) -> str:
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    return slugify(f"{date}-{source}-{message_id or 'manual'}")


def detect_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}:
        return "image"
    if suffix in {".ogg", ".oga", ".opus"}:
        return "voice"
    if suffix in {".mp3", ".wav", ".m4a", ".flac"}:
        return "audio"
    if suffix in {".mp4", ".mov", ".mkv", ".webm"}:
        return "video"
    if suffix == ".pdf":
        return "pdf"
    return "text"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "request"


def _safe_original_name(name: str, media_type: str) -> str:
    safe = Path(name).name
    if "." in safe:
        return safe
    extension = {
        "image": ".jpg",
        "voice": ".ogg",
        "audio": ".audio",
        "video": ".mp4",
        "pdf": ".pdf",
        "text": ".txt",
    }.get(media_type, ".bin")
    return f"original{extension}"
