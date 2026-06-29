from __future__ import annotations

from dataclasses import replace

from .config import Settings
from .git_push import GitRepository


def prepare_capture_settings(settings: Settings, *, request_id: str) -> Settings:
    settings.validate_delivery_mode()
    if not settings.uses_pull_requests:
        GitRepository(settings).assert_clean_for_capture()
        return settings

    worktree_path, branch = GitRepository(settings).create_capture_worktree(request_id=request_id)
    return replace(
        settings,
        content_repo_path=worktree_path,
        git_capture_branch=branch,
    )
