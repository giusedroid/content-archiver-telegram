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
from .workflows import workflow_path


app = typer.Typer(help="Telegram ingress for the Kiro-operated content archive.")


def _settings() -> Settings:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return Settings.from_env()


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
def search(query: str) -> None:
    result = KiroRunner(_settings()).run_search(query=query)
    typer.echo(result.get("message") or result)
