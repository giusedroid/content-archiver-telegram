from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def _bool_env(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _int_set_env(value: str | None) -> set[int]:
    if value is None or value.strip() == "":
        return set()
    ids: set[int] = set()
    for token in re.split(r"[\s,;]+", value.strip()):
        if not token:
            continue
        try:
            ids.add(int(token))
        except ValueError as exc:
            raise RuntimeError(f"TELEGRAM_ALLOWED_USER_IDS contains a non-integer: {token}") from exc
    return ids


@dataclass(slots=True)
class Settings:
    telegram_bot_token: str | None = None
    telegram_allowed_user_ids: set[int] = field(default_factory=set)
    telegram_allow_all_users: bool = False
    content_repo_path: Path = Path("../content-archive-repo")
    telegram_download_dir: Path = Path(".content-archiver-telegram/downloads")
    kiro_cli: str | None = None
    kiro_api_key: str | None = None
    kiro_trust_tools: str = "read,grep,write,bash"
    kiro_timeout_seconds: int = 600

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_allowed_user_ids=_int_set_env(os.getenv("TELEGRAM_ALLOWED_USER_IDS")),
            telegram_allow_all_users=_bool_env(os.getenv("TELEGRAM_ALLOW_ALL_USERS"), False),
            content_repo_path=Path(os.getenv("CONTENT_REPO_PATH", "../content-archive-repo")),
            telegram_download_dir=Path(
                os.getenv("TELEGRAM_DOWNLOAD_DIR", ".content-archiver-telegram/downloads")
            ),
            kiro_cli=os.getenv("KIRO_CLI") or None,
            kiro_api_key=os.getenv("KIRO_API_KEY") or None,
            kiro_trust_tools=os.getenv("KIRO_TRUST_TOOLS", "read,grep,write,bash").strip()
            or "read,grep,write,bash",
            kiro_timeout_seconds=int(os.getenv("KIRO_TIMEOUT_SECONDS", "600")),
        ).resolve_paths()

    def resolve_paths(self) -> "Settings":
        self.content_repo_path = self.content_repo_path.resolve()
        self.telegram_download_dir = self.telegram_download_dir.resolve()
        return self

    def validate_telegram_security(self) -> None:
        if self.telegram_allow_all_users or self.telegram_allowed_user_ids:
            return
        raise RuntimeError(
            "TELEGRAM_ALLOWED_USER_IDS is required unless TELEGRAM_ALLOW_ALL_USERS=true."
        )

    def validate_kiro(self) -> None:
        if self.kiro_cli:
            return
        raise RuntimeError("KIRO_CLI is required to run content repository workflows.")
