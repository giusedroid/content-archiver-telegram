from __future__ import annotations

import asyncio
from types import SimpleNamespace

from content_archiver_telegram.config import Settings
from content_archiver_telegram.incoming import IncomingRequest
from content_archiver_telegram.telegram_bot import (
    _download,
    _failure_message,
    _intro_message,
    _result_message,
)


class FakeTelegramFile:
    def __init__(self) -> None:
        self.download_path = None

    async def download_to_drive(self, custom_path) -> None:
        self.download_path = custom_path
        custom_path.write_bytes(b"telegram-file")


def test_download_uses_temp_file_inside_download_directory(tmp_path) -> None:
    telegram_file = FakeTelegramFile()

    async def get_file(file_id: str):
        assert file_id == "file-id"
        return telegram_file

    context = SimpleNamespace(bot=SimpleNamespace(get_file=get_file))
    settings = Settings(telegram_download_dir=tmp_path).resolve_paths()

    target = asyncio.run(_download(context, "file-id", settings, "photo.jpg"))

    assert target == tmp_path / "photo.jpg"
    assert target.read_bytes() == b"telegram-file"
    assert telegram_file.download_path.parent == tmp_path
    assert not telegram_file.download_path.exists()


def test_intro_message_describes_request_and_media_plan() -> None:
    request = IncomingRequest(
        id="2026-06-29-telegram-12345678",
        media_type="image",
        caption="AWS London Summit",
    )

    message = _intro_message(request)

    assert "12345678" in message
    assert "`image` capture" in message
    assert "create a preview" in message


def test_result_message_includes_pr_url() -> None:
    request = IncomingRequest(id="2026-06-29-telegram-12345678", media_type="image")
    settings = Settings(capture_delivery_mode="pull-request")
    result = {
        "message": "Archived under captures/aws-london.",
        "capture_id": "aws-london",
        "git_pr": {"url": "https://github.com/o/r/pull/9"},
    }

    message = _result_message(request, result, settings)

    assert "Kiro summary: Archived under captures/aws-london." in message
    assert "`captures/aws-london/`" in message
    assert "https://github.com/o/r/pull/9" in message


def test_failure_message_says_no_commit_or_pr() -> None:
    request = IncomingRequest(
        id="2026-06-30-telegram-44",
        source="telegram",
        source_message_id="44",
        media_type="image",
    )

    message = _failure_message(request, RuntimeError("Kiro completed without MCP tools mounted."))

    assert "egram-44" in message
    assert "failed before commit" in message
    assert "did not commit or open a PR" in message
