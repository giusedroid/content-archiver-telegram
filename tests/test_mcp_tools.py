from content_archiver_telegram.mcp_tools import (
    ToolSettings,
    index_lancedb,
    semantic_search,
    transcribe_audio,
    upload_original_to_s3,
)


def test_upload_original_to_s3_dry_run_copies_blob(tmp_path) -> None:
    source = tmp_path / "incoming.jpg"
    source.write_bytes(b"image")
    settings = ToolSettings(
        content_repo_path=tmp_path,
        s3_bucket="content-archive",
        s3_dry_run=True,
    )

    result = upload_original_to_s3(
        local_path=str(source),
        capture_id="aws-london-summit-2026",
        asset_id="image-001",
        original_filename="photo.jpg",
        settings=settings,
    )

    assert result == {
        "original_uri": "s3://content-archive/raw/aws-london-summit-2026/image-001/photo.jpg"
    }
    assert (
        tmp_path
        / ".content-archiver"
        / "blob-store"
        / "raw"
        / "aws-london-summit-2026"
        / "image-001"
        / "photo.jpg"
    ).read_bytes() == b"image"


def test_index_lancedb_and_semantic_search_local_fallback(tmp_path) -> None:
    capture_dir = tmp_path / "captures" / "aws-london-summit-2026"
    capture_dir.mkdir(parents=True)
    (capture_dir / "capture.md").write_text(
        "# AWS London Summit 2026\n\nInterview with Jeff Barr about AWS.",
        encoding="utf-8",
    )
    settings = ToolSettings(content_repo_path=tmp_path, embedding_provider="stub")

    report = index_lancedb(settings=settings)
    result = semantic_search("Jeff Barr AWS", settings=settings)

    assert report["scanned_files"] == 1
    assert report["changed_files"] == 1
    assert report["chunks"] == 1
    assert report["report_path"] == "index/index-report.json"
    assert result["results"][0]["capture_id"] == "aws-london-summit-2026"
    assert result["results"][0]["path"] == "captures/aws-london-summit-2026/capture.md"


def test_transcribe_audio_stub(tmp_path) -> None:
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"audio")
    settings = ToolSettings(content_repo_path=tmp_path, transcription_provider="stub")

    result = transcribe_audio(str(audio), settings=settings)

    assert "Transcription disabled" in result["transcript"]
