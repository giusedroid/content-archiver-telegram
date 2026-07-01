from __future__ import annotations

import logging
import os
from pathlib import Path

import typer

from .capture_workspace import prepare_capture_settings
from .config import Settings
from .incoming import IncomingRequest, detect_media_type, request_id, write_incoming_request
from .kiro_runner import KiroRunner
from .preprocessor import preprocess_request
from .search import format_search_result, index_archive, search_archive
from .workflows import workflow_path


app = typer.Typer(help="Telegram ingress for the Kiro-operated content archive.")


def _settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or None
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if token:
        redaction_filter = _SecretRedactionFilter([token])
        logging.getLogger().addFilter(redaction_filter)
        for handler in logging.getLogger().handlers:
            handler.addFilter(redaction_filter)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return Settings.from_env()


class _SecretRedactionFilter(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self.secrets = [secret for secret in secrets if secret]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.secrets:
            return True
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "***")
        record.msg = message
        record.args = ()
        return True


@app.command()
def serve() -> None:
    from .telegram_bot import run_bot

    run_bot(_settings())


@app.command("process-file")
def process_file(
    path: str,
    caption: str | None = typer.Option(None, "--caption"),
    media_type: str | None = typer.Option(None, "--media-type"),
) -> None:
    settings = _settings()
    source = Path(path).resolve()
    detected = media_type or detect_media_type(source)
    request = IncomingRequest(
        id=request_id(source="local-file", message_id=source.stem),
        source="local-file",
        media_type=detected,
        caption=caption,
        source_message_id=source.stem,
    )
    request_settings = prepare_capture_settings(settings, request_id=request.id)
    request_path = write_incoming_request(
        content_repo_path=request_settings.content_repo_path,
        request=request,
        source_file=source,
    )
    preprocess_request(request_settings, request_path)
    result = KiroRunner(request_settings).run_workflow(
        workflow_path=workflow_path(request_settings.content_repo_path, detected),
        request_path=request_path,
    )
    typer.echo(result.get("message") or result)


@app.command()
def index() -> None:
    result = index_archive(_settings())
    typer.echo(result)


@app.command()
def search(query: str, limit: int = typer.Option(10, "--limit", "-n")) -> None:
    result = search_archive(_settings(), query=query, limit=limit)
    typer.echo(format_search_result(result))
