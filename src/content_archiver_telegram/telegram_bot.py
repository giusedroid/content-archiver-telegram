from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from .capture_workspace import prepare_capture_settings
from .config import Settings
from .git_push import GitPushError, GitRepository
from .incoming import IncomingRequest, request_id, write_incoming_request
from .kiro_runner import KiroRunner, KiroRunError
from .preprocessor import PreprocessError, preprocess_request
from .search import format_search_result, search_archive
from .workflows import workflow_path


def run_bot(settings: Settings) -> None:
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
    except ImportError as exc:
        raise RuntimeError("python-telegram-bot is required to run the Telegram bot.") from exc

    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required.")
    settings.validate_telegram_security()

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update, settings):
            await _reject(update)
            return
        await update.effective_message.reply_text("Content archive bot is ready.")

    async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update, settings):
            await _reject(update)
            return
        query = " ".join(context.args).strip()
        if not query:
            await update.effective_message.reply_text("Usage: /search <query>")
            return
        result = await asyncio.to_thread(search_archive, settings, query=query)
        await update.effective_message.reply_text(format_search_result(result))

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update, settings):
            await _reject(update)
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /status <request-id>")
            return
        if not settings.uses_pull_requests:
            await update.effective_message.reply_text("This bot is running in direct commit mode.")
            return
        request_id_value = context.args[0].strip()
        try:
            result = await asyncio.to_thread(_find_request_pr, settings, request_id_value)
        except GitPushError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        if result.url:
            await update.effective_message.reply_text(
                f"Request `{request_id_value}` is on branch `{result.branch}`.\nPR: {result.url}"
            )
        else:
            await update.effective_message.reply_text(
                f"I found branch `{result.branch}`, but no pull request yet."
            )

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update, settings):
            await _reject(update)
            return
        request, source_file = await _request_from_update(update, context, settings)
        if settings.telegram_chatty:
            await update.effective_message.reply_text(_intro_message(request))
        try:
            request_settings = prepare_capture_settings(settings, request_id=request.id)
        except GitPushError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        request_path = write_incoming_request(
            content_repo_path=request_settings.content_repo_path,
            request=request,
            source_file=source_file,
        )
        if settings.telegram_chatty:
            await update.effective_message.reply_text(_preprocess_message(request))
        try:
            await asyncio.to_thread(preprocess_request, request_settings, request_path)
        except PreprocessError as exc:
            await update.effective_message.reply_text(_failure_message(request, exc))
            return
        if settings.telegram_chatty:
            await update.effective_message.reply_text(_analysis_message(request))
        try:
            result = await asyncio.to_thread(
                _run_capture_workflow,
                request_settings,
                request,
                request_path,
            )
        except KiroRunError as exc:
            await update.effective_message.reply_text(_failure_message(request, exc))
            return
        await update.effective_message.reply_text(_result_message(request, result, settings))

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    app.run_polling()


def _run_capture_workflow(
    settings: Settings,
    request: IncomingRequest,
    request_path: Path,
) -> dict[str, Any]:
    return KiroRunner(settings).run_workflow(
        workflow_path=workflow_path(settings.content_repo_path, request.media_type),
        request_path=request_path,
    )


def _find_request_pr(settings: Settings, request_id_value: str):
    from .git_push import request_branch_name

    branch = request_branch_name(settings.git_branch_prefix, request_id_value)
    return GitRepository(settings).find_pull_request_for_branch(branch=branch)


async def _request_from_update(update: Any, context: Any, settings: Settings) -> tuple[IncomingRequest, Path | None]:
    message = update.effective_message
    message_id = str(message.message_id)
    base = {
        "id": request_id(source="telegram", message_id=message_id),
        "source": "telegram",
        "source_message_id": message_id,
        "caption": message.caption,
        "telegram": {
            "user_id": _user_id(update),
            "chat_id": getattr(getattr(update, "effective_chat", None), "id", None),
        },
    }

    if message.photo:
        photo = message.photo[-1]
        path = await _download(context, photo.file_id, settings, f"{message_id}.jpg")
        return IncomingRequest(media_type="image", **base), path
    if message.voice:
        path = await _download(context, message.voice.file_id, settings, f"{message_id}.ogg")
        return IncomingRequest(media_type="voice", **base), path
    if message.video:
        filename = message.video.file_name or f"{message_id}.mp4"
        path = await _download(context, message.video.file_id, settings, filename)
        return IncomingRequest(media_type="video", **base), path
    if message.document:
        filename = message.document.file_name or f"{message_id}.bin"
        path = await _download(context, message.document.file_id, settings, filename)
        media_type = "pdf" if filename.lower().endswith(".pdf") else "text"
        return IncomingRequest(media_type=media_type, **base), path

    text = message.text or message.caption or ""
    media_type = "link" if "http://" in text or "https://" in text else "text"
    return IncomingRequest(media_type=media_type, text=text, **base), None


async def _download(context: Any, file_id: str, settings: Settings, filename: str) -> Path:
    settings.telegram_download_dir.mkdir(parents=True, exist_ok=True)
    target = settings.telegram_download_dir / Path(filename).name
    telegram_file = await context.bot.get_file(file_id)
    with tempfile.NamedTemporaryFile(
        dir=settings.telegram_download_dir,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp:
        temp_path = Path(temp.name)
    try:
        await telegram_file.download_to_drive(custom_path=temp_path)
        temp_path.replace(target)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return target


def _authorized(update: Any, settings: Settings) -> bool:
    if settings.telegram_allow_all_users:
        return True
    user_id = _user_id(update)
    return user_id is not None and user_id in settings.telegram_allowed_user_ids


async def _reject(update: Any) -> None:
    user_id = _user_id(update)
    suffix = f" Your Telegram user id is {user_id}." if user_id is not None else ""
    await update.effective_message.reply_text(f"This bot is private.{suffix}")


def _user_id(update: Any) -> int | None:
    user = getattr(update, "effective_user", None)
    value = getattr(user, "id", None)
    return int(value) if value is not None else None


def _intro_message(request: IncomingRequest) -> str:
    return (
        f"Cool, this is request `{request.id}` "
        f"(short `{_short_request_id(request.id)}`).\n"
        f"It looks like {article(request.media_type)} `{request.media_type}` capture, so I will "
        f"{_media_plan(request.media_type)}."
    )


def _analysis_message(request: IncomingRequest) -> str:
    return (
        f"I enriched the intake file for `{_short_request_id(request.id)}` and handed it to Kiro. "
        "I am checking repository context and doing the semantic pass now."
    )


def _preprocess_message(request: IncomingRequest) -> str:
    return (
        f"I wrote the intake file for `{_short_request_id(request.id)}`. "
        "I am running the archive MCP tools deterministically before Kiro."
    )


def _result_message(request: IncomingRequest, result: dict[str, Any], settings: Settings) -> str:
    message = str(result.get("message") or "Kiro completed the capture workflow.")
    capture_id = result.get("capture_id")
    paths = result.get("paths") if isinstance(result.get("paths"), list) else []
    location = f"`captures/{capture_id}/`" if capture_id else "the proposed inbox/capture paths"
    if paths:
        location = ", ".join(f"`{path}`" for path in paths[:3])

    lines = [
        f"Cool, request `{_short_request_id(request.id)}` is processed.",
        f"Kiro summary: {message}",
        f"I am proposing to save it under {location}.",
    ]
    pr = result.get("git_pr") if isinstance(result.get("git_pr"), dict) else {}
    if pr.get("url"):
        lines.append(f"Can you have a look at this PR for request `{request.id}`? {pr['url']}")
    elif settings.uses_pull_requests:
        lines.append("I did not get a PR URL back, so check the branch/push result before merging.")
    return "\n".join(lines)


def _failure_message(request: IncomingRequest, exc: Exception) -> str:
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else "Kiro failed."
    return (
        f"Request `{_short_request_id(request.id)}` failed before commit.\n"
        f"{detail}\n"
        "I did not commit or open a PR for this capture."
    )


def _short_request_id(request_id_value: str) -> str:
    return request_id_value[-8:]


def _media_plan(media_type: str) -> str:
    plans = {
        "image": "upload the original, create a preview, classify the capture, and draft archive files",
        "video": "upload the original, extract audio and frames, transcribe, classify, and draft archive files",
        "voice": "upload the original, transcribe it, classify the capture, and draft archive files",
        "audio": "upload the original, transcribe it, classify the capture, and draft archive files",
        "pdf": "upload the original, convert it to markdown, classify it, and draft archive files",
        "link": "crawl the page, classify it, and draft archive files",
        "text": "classify it and draft archive files",
    }
    return plans.get(media_type, "classify it and draft archive files")


def article(word: str) -> str:
    return "an" if word[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
