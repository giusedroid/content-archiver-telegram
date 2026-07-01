from __future__ import annotations

from pathlib import Path

import yaml

from content_archiver_telegram.config import Settings
from content_archiver_telegram.preprocessor import preprocess_request


class FakeMCPClient:
    calls = []

    def __init__(self, settings):
        self.settings = settings

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def call_tool(self, name, arguments):
        self.__class__.calls.append((name, arguments))
        if name == "upload_original_to_s3":
            return {"original_uri": "s3://bucket/raw/_intake/request/image.jpg"}
        if name == "resize_image":
            return {"output_path": arguments["output_path"]}
        if name == "extract_audio":
            return {"audio_path": arguments["output_path"]}
        if name == "extract_video_frames":
            return {"frame_paths": [f"{arguments['output_dir']}/frame-001.jpg"]}
        if name == "transcribe_audio":
            return {"transcript": "# Transcript\n\nhello"}
        if name == "pdf_to_markdown":
            return {"markdown_path": arguments["output_path"]}
        if name == "crawl_url_to_markdown":
            return {"markdown_path": arguments["output_path"]}
        raise AssertionError(name)


def setup_function() -> None:
    FakeMCPClient.calls = []


def _request_file(tmp_path: Path, media_type: str, **extra) -> Path:
    request_dir = tmp_path / ".content-archiver" / "incoming" / "request-1"
    request_dir.mkdir(parents=True)
    data = {
        "id": "request-1",
        "media_type": media_type,
        "local_original_path": ".content-archiver/incoming/request-1/original.bin",
        "caption": None,
        "text": None,
    }
    data.update(extra)
    path = request_dir / "request.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_preprocess_image_writes_results_to_request(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("content_archiver_telegram.preprocessor.StdioMCPClient", FakeMCPClient)
    request_path = _request_file(tmp_path, "image")

    result = preprocess_request(Settings(content_repo_path=tmp_path), request_path)

    assert result["status"] == "completed"
    assert [call[0] for call in FakeMCPClient.calls] == ["upload_original_to_s3", "resize_image"]
    data = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    assert data["preprocessing"]["steps"][1]["result"]["output_path"].endswith("previews/image.jpg")


def test_preprocess_video_extracts_frames_audio_and_transcript(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("content_archiver_telegram.preprocessor.StdioMCPClient", FakeMCPClient)
    request_path = _request_file(tmp_path, "video")

    preprocess_request(Settings(content_repo_path=tmp_path), request_path)

    assert [call[0] for call in FakeMCPClient.calls] == [
        "upload_original_to_s3",
        "extract_video_frames",
        "extract_audio",
        "transcribe_audio",
    ]
    transcript = (
        tmp_path
        / ".content-archiver"
        / "incoming"
        / "request-1"
        / "transcripts"
        / "transcript.md"
    )
    assert "hello" in transcript.read_text(encoding="utf-8")


def test_preprocess_can_be_disabled(tmp_path) -> None:
    request_path = _request_file(tmp_path, "image")

    result = preprocess_request(
        Settings(content_repo_path=tmp_path, archive_mcp_preprocess=False),
        request_path,
    )

    assert result["status"] == "skipped"
    data = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    assert "preprocessing" not in data
