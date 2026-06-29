from content_archiver_telegram.capture_workspace import prepare_capture_settings
from content_archiver_telegram.config import Settings


class FakeGitRepository:
    clean_checked = False
    created_request = None

    def __init__(self, settings):
        self.settings = settings

    def assert_clean_for_capture(self) -> None:
        self.__class__.clean_checked = True

    def create_capture_worktree(self, *, request_id: str):
        self.__class__.created_request = request_id
        return self.settings.git_worktree_root / request_id, f"capture/{request_id}"


def setup_function() -> None:
    FakeGitRepository.clean_checked = False
    FakeGitRepository.created_request = None


def test_prepare_capture_settings_checks_clean_repo_in_commit_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "content_archiver_telegram.capture_workspace.GitRepository",
        FakeGitRepository,
    )
    settings = Settings(content_repo_path=tmp_path)

    result = prepare_capture_settings(settings, request_id="telegram-9")

    assert result is settings
    assert FakeGitRepository.clean_checked is True


def test_prepare_capture_settings_uses_worktree_in_pr_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "content_archiver_telegram.capture_workspace.GitRepository",
        FakeGitRepository,
    )
    settings = Settings(
        content_repo_path=tmp_path / "repo",
        git_worktree_root=tmp_path / "worktrees",
        capture_delivery_mode="pull-request",
        github_token="token",
    )

    result = prepare_capture_settings(settings, request_id="telegram-9")

    assert result.content_repo_path == tmp_path / "worktrees" / "telegram-9"
    assert result.git_capture_branch == "capture/telegram-9"
    assert FakeGitRepository.created_request == "telegram-9"
