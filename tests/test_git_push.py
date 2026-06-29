import base64
import json
import subprocess

import pytest

from content_archiver_telegram.config import Settings
from content_archiver_telegram.git_push import (
    GitPushError,
    GitRepository,
    request_branch_name,
    safe_path_name,
)


def _completed(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=args,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_git_commit_all_if_changed_creates_commit(monkeypatch, tmp_path) -> None:
    calls = []
    heads = iter(["old-head\n", "new-head\n"])

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["git", "rev-parse", "--verify"]:
            return _completed(args, stdout=next(heads))
        if args[:3] == ["git", "status", "--porcelain"]:
            return _completed(args, stdout="?? captures/new-item/capture.md\n")
        if args[:3] == ["git", "add", "-A"]:
            return _completed(args)
        if args[:3] == ["git", "commit", "-m"]:
            return _completed(args)
        raise AssertionError(args)

    monkeypatch.setattr("content_archiver_telegram.git_push.subprocess.run", fake_run)

    result = GitRepository(Settings(content_repo_path=tmp_path)).commit_all_if_changed(
        message="capture: add new-item image"
    )

    assert result.changed is True
    assert result.committed is True
    assert result.before_head == "old-head"
    assert result.after_head == "new-head"
    assert result.message == "capture: add new-item image"
    assert ["git", "add", "-A"] in calls
    assert ["git", "commit", "-m", "capture: add new-item image"] in calls


def test_git_commit_all_if_changed_skips_clean_repo(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["git", "rev-parse", "--verify"]:
            return _completed(args, stdout="same-head\n")
        if args[:3] == ["git", "status", "--porcelain"]:
            return _completed(args, stdout="")
        raise AssertionError(args)

    monkeypatch.setattr("content_archiver_telegram.git_push.subprocess.run", fake_run)

    result = GitRepository(Settings(content_repo_path=tmp_path)).commit_all_if_changed(
        message="capture: add clean item"
    )

    assert result.changed is False
    assert result.committed is False
    assert result.before_head == "same-head"
    assert result.after_head == "same-head"
    assert all("commit" not in call for call in calls)


def test_git_assert_clean_for_capture_allows_clean_repo(monkeypatch, tmp_path) -> None:
    def fake_run(args, **kwargs):
        if args[:3] == ["git", "status", "--porcelain"]:
            return _completed(args, stdout="")
        raise AssertionError(args)

    monkeypatch.setattr("content_archiver_telegram.git_push.subprocess.run", fake_run)

    GitRepository(Settings(content_repo_path=tmp_path)).assert_clean_for_capture()


def test_git_assert_clean_for_capture_rejects_dirty_repo(monkeypatch, tmp_path) -> None:
    def fake_run(args, **kwargs):
        if args[:3] == ["git", "status", "--porcelain"]:
            return _completed(args, stdout="?? captures/partial/capture.md\n")
        raise AssertionError(args)

    monkeypatch.setattr("content_archiver_telegram.git_push.subprocess.run", fake_run)

    with pytest.raises(GitPushError, match="uncommitted changes"):
        GitRepository(Settings(content_repo_path=tmp_path)).assert_clean_for_capture()


def test_git_create_capture_worktree_creates_request_branch(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _completed(args)

    monkeypatch.setattr("content_archiver_telegram.git_push.subprocess.run", fake_run)
    settings = Settings(
        content_repo_path=tmp_path / "repo",
        git_worktree_root=tmp_path / "worktrees",
        git_branch="main",
        git_branch_prefix="capture",
    )

    path, branch = GitRepository(settings).create_capture_worktree(
        request_id="2026-06-29 telegram/9"
    )

    assert path == tmp_path / "worktrees" / "2026-06-29-telegram-9"
    assert branch == "capture/2026-06-29-telegram-9"
    assert calls == [
        [
            "git",
            "worktree",
            "add",
            "-b",
            "capture/2026-06-29-telegram-9",
            str(path),
            "main",
        ]
    ]


def test_git_request_branch_helpers() -> None:
    assert safe_path_name("hello / there") == "hello-there"
    assert request_branch_name("capture", "telegram/123") == "capture/telegram-123"


def test_git_push_uses_temporary_github_auth_header(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["git", "rev-parse", "--verify"]:
            return _completed(args, stdout="new-head\n")
        if args[0] == "git" and "push" in args:
            return _completed(args)
        raise AssertionError(args)

    monkeypatch.setattr("content_archiver_telegram.git_push.subprocess.run", fake_run)
    settings = Settings(
        content_repo_path=tmp_path,
        git_push=True,
        git_remote="origin",
        git_branch="main",
        github_token="github_pat_secret",
        github_username="giusedroid",
    )

    result = GitRepository(settings).push_if_head_changed(before_head="old-head")

    assert result.pushed is True
    push_call = calls[-1]
    assert push_call[:4] == ["git", "-c", push_call[2], "push"]
    assert push_call[-2:] == ["origin", "HEAD:main"]
    assert "github_pat_secret" not in push_call[2]

    encoded = push_call[2].split("Basic ", 1)[1]
    assert base64.b64decode(encoded).decode("utf-8") == "giusedroid:github_pat_secret"


def test_git_push_branch_uses_capture_branch(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _completed(args)

    monkeypatch.setattr("content_archiver_telegram.git_push.subprocess.run", fake_run)
    settings = Settings(
        content_repo_path=tmp_path,
        capture_delivery_mode="pull-request",
        github_token="github_pat_secret",
    )

    GitRepository(settings).push_branch(branch="capture/telegram-9")

    assert calls[-1][-2:] == ["origin", "HEAD:refs/heads/capture/telegram-9"]
    assert "github_pat_secret" not in calls[-1][2]


class FakeResponse:
    def __init__(self, payload: dict | list) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_git_create_pull_request_uses_github_api(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.headers["Authorization"]
        return FakeResponse({"html_url": "https://github.com/o/r/pull/7", "number": 7})

    monkeypatch.setattr("content_archiver_telegram.git_push.urlopen", fake_urlopen)
    settings = Settings(
        content_repo_path=tmp_path,
        capture_delivery_mode="pull-request",
        github_token="github_pat_secret",
        github_repository="o/r",
    )

    result = GitRepository(settings).create_pull_request(
        branch="capture/telegram-9",
        title="Capture telegram-9",
        body="body",
    )

    assert captured["url"] == "https://api.github.com/repos/o/r/pulls"
    assert captured["method"] == "POST"
    assert captured["payload"]["head"] == "capture/telegram-9"
    assert captured["payload"]["base"] == "main"
    assert captured["authorization"] == "Bearer github_pat_secret"
    assert result.url == "https://github.com/o/r/pull/7"
    assert result.number == 7


def test_git_push_skips_when_head_did_not_change(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _completed(args, stdout="same-head\n")

    monkeypatch.setattr("content_archiver_telegram.git_push.subprocess.run", fake_run)
    settings = Settings(content_repo_path=tmp_path, git_push=True, github_token="token")

    result = GitRepository(settings).push_if_head_changed(before_head="same-head")

    assert result.pushed is False
    assert all("push" not in call for call in calls)


def test_git_push_redacts_token_on_failure(monkeypatch, tmp_path) -> None:
    def fake_run(args, **kwargs):
        if args[:3] == ["git", "rev-parse", "--verify"]:
            return _completed(args, stdout="new-head\n")
        return _completed(args, returncode=1, stderr="bad token github_pat_secret")

    monkeypatch.setattr("content_archiver_telegram.git_push.subprocess.run", fake_run)
    settings = Settings(
        content_repo_path=tmp_path,
        git_push=True,
        github_token="github_pat_secret",
    )

    with pytest.raises(GitPushError) as exc_info:
        GitRepository(settings).push_if_head_changed(before_head="old-head")

    encoded = base64.b64encode(b"x-access-token:github_pat_secret").decode("ascii")
    assert "github_pat_secret" not in str(exc_info.value)
    assert encoded not in str(exc_info.value)
    assert ".extraheader=***" in str(exc_info.value)
    assert "***" in str(exc_info.value)
