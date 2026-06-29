from __future__ import annotations

from pathlib import Path

import typer

from .config import Settings
from .git_push import GitRepository
from .incoming import IncomingRequest, detect_media_type, request_id, write_incoming_request
from .kiro_runner import KiroRunner
from .workflows import workflow_path


app = typer.Typer(help="Telegram ingress for the Kiro-operated content archive.")


def _settings() -> Settings:
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
    GitRepository(settings).assert_clean_for_capture()
    source = Path(path).resolve()
    detected = media_type or detect_media_type(source)
    request = IncomingRequest(
        id=request_id(source="local-file", message_id=source.stem),
        source="local-file",
        media_type=detected,
        caption=caption,
        source_message_id=source.stem,
    )
    request_path = write_incoming_request(
        content_repo_path=settings.content_repo_path,
        request=request,
        source_file=source,
    )
    result = KiroRunner(settings).run_workflow(
        workflow_path=workflow_path(settings.content_repo_path, detected),
        request_path=request_path,
    )
    typer.echo(result.get("message") or result)


@app.command()
def search(query: str) -> None:
    result = KiroRunner(_settings()).run_search(query=query)
    typer.echo(result.get("message") or result)
