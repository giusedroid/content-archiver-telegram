import pytest

from content_archiver_telegram.config import Settings


def test_allowed_user_ids_parse_commas_spaces_and_semicolons(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1, 2;3 1")

    assert Settings.from_env().telegram_allowed_user_ids == {1, 2, 3}


def test_telegram_security_requires_allowlist() -> None:
    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_USER_IDS"):
        Settings().validate_telegram_security()

    Settings(telegram_allowed_user_ids={1}).validate_telegram_security()
    Settings(telegram_allow_all_users=True).validate_telegram_security()


def test_git_push_settings_parse_from_env(monkeypatch) -> None:
    monkeypatch.setenv("GIT_PUSH", "true")
    monkeypatch.setenv("GIT_REMOTE", "archive")
    monkeypatch.setenv("GIT_BRANCH", "captures")
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_secret")
    monkeypatch.setenv("GITHUB_USERNAME", "giusedroid")

    settings = Settings.from_env()

    assert settings.git_push is True
    assert settings.git_remote == "archive"
    assert settings.git_branch == "captures"
    assert settings.github_token == "github_pat_secret"
    assert settings.github_username == "giusedroid"


def test_pull_request_delivery_settings_parse_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CAPTURE_DELIVERY_MODE", "pull-request")
    monkeypatch.setenv("GIT_WORKTREE_ROOT", "worktrees")
    monkeypatch.setenv("GIT_BRANCH_PREFIX", "archive")
    monkeypatch.setenv("GITHUB_REPOSITORY", "giusedroid/content-archive")
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_secret")

    settings = Settings.from_env()

    assert settings.uses_pull_requests is True
    assert settings.git_worktree_root.name == "worktrees"
    assert settings.git_branch_prefix == "archive"
    assert settings.github_repository == "giusedroid/content-archive"
    settings.validate_delivery_mode()


def test_git_push_requires_token_when_enabled() -> None:
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        Settings(git_push=True).validate_git_push()


def test_pull_request_delivery_requires_token() -> None:
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        Settings(capture_delivery_mode="pull-request").validate_delivery_mode()


def test_kiro_requires_mcp_startup_by_default(monkeypatch) -> None:
    monkeypatch.delenv("KIRO_REQUIRE_MCP_STARTUP", raising=False)

    assert Settings.from_env().kiro_require_mcp_startup is True


def test_kiro_require_mcp_startup_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("KIRO_REQUIRE_MCP_STARTUP", "false")

    assert Settings.from_env().kiro_require_mcp_startup is False
