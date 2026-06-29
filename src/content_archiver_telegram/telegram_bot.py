from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .config import Settings
from .incoming import IncomingRequest, request_id, write_incoming_request
from .kiro_runner import KiroRunner
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
        result = KiroRunner(settings).run_search(query=query)
        await update.effective_message.reply_text(str(result.get("message") or result))

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update, settings):
            await _reject(update)
            return
        request, source_file = await _request_from_update(update, context, settings)
        request_path = write_incoming_request(
            content_repo_path=settings.content_repo_path,
            request=request,
            source_file=source_file,
        )
        result = KiroRunner(settings).run_workflow(
            workflow_path=workflow_path(settings.content_repo_path, request.media_type),
            request_path=request_path,
        )
        await update.effective_message.reply_text(str(result.get("message") or result))

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    app.run_polling()


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
    with tempfile.NamedTemporaryFile(delete=False) as temp:
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
