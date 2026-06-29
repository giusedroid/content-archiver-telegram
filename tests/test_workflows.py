from pathlib import Path

import pytest

from content_archiver_telegram.incoming import IncomingRequest, detect_media_type, write_incoming_request
from content_archiver_telegram.workflows import workflow_path


def test_detect_media_type() -> None:
    assert detect_media_type(Path("photo.jpg")) == "image"
    assert detect_media_type(Path("clip.mp4")) == "video"
    assert detect_media_type(Path("voice.ogg")) == "voice"
    assert detect_media_type(Path("doc.pdf")) == "pdf"


def test_write_incoming_request_copies_file_and_writes_yaml(tmp_path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"image")

    request_path = write_incoming_request(
        content_repo_path=tmp_path,
        request=IncomingRequest(id="telegram-1", media_type="image", caption="AWS Summit"),
        source_file=source,
    )

    assert request_path == tmp_path / ".content-archiver" / "incoming" / "telegram-1" / "request.yml"
    assert "caption: AWS Summit" in request_path.read_text(encoding="utf-8")
    assert (request_path.parent / "source.jpg").exists()


def test_workflow_path_requires_existing_prompt(tmp_path) -> None:
    workflow = tmp_path / ".kiro" / "workflows" / "capture-image.md"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("workflow", encoding="utf-8")

    assert workflow_path(tmp_path, "image") == workflow

    with pytest.raises(ValueError):
        workflow_path(tmp_path, "unknown")
