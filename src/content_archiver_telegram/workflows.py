from __future__ import annotations

from pathlib import Path


WORKFLOW_BY_MEDIA_TYPE = {
    "image": ".kiro/workflows/capture-image.md",
    "video": ".kiro/workflows/capture-video.md",
    "voice": ".kiro/workflows/capture-audio.md",
    "audio": ".kiro/workflows/capture-audio.md",
    "pdf": ".kiro/workflows/capture-pdf.md",
    "link": ".kiro/workflows/capture-link.md",
    "text": ".kiro/workflows/capture-text.md",
    "search": ".kiro/workflows/search.md",
}


def workflow_path(content_repo_path: Path, media_type: str) -> Path:
    try:
        relative = WORKFLOW_BY_MEDIA_TYPE[media_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported media type: {media_type}") from exc
    path = content_repo_path / relative
    if not path.exists():
        raise FileNotFoundError(f"Workflow prompt not found: {path}")
    return path
