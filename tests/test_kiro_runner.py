import json
import subprocess

from content_archiver_telegram.config import Settings
from content_archiver_telegram.git_push import GitCommitResult, GitPullRequestResult, GitPushResult
from content_archiver_telegram.kiro_runner import KiroRunner


class FakeGitRepository:
    committed_messages = []
    pushed_from = []
    pushed_branches = []
    created_prs = []

    def __init__(self, settings):
        self.settings = settings

    def current_head(self):
        return "old-head"

    def commit_all_if_changed(self, *, message: str):
        self.__class__.committed_messages.append(message)
        return GitCommitResult(
            changed=True,
            committed=True,
            before_head="old-head",
            after_head="new-head",
            message=message,
        )

    def push_if_head_changed(self, *, before_head: str):
        self.__class__.pushed_from.append(before_head)
        return GitPushResult(
            enabled=self.settings.git_push,
            pushed=self.settings.git_push,
            remote=self.settings.git_remote,
            branch=self.settings.git_branch,
            before_head=before_head,
            after_head="new-head",
        )

    def push_branch(self, *, branch: str) -> None:
        self.__class__.pushed_branches.append(branch)

    def create_pull_request(self, *, branch: str, title: str, body: str):
        self.__class__.created_prs.append((branch, title, body))
        return GitPullRequestResult(
            enabled=True,
            pushed=True,
            created=True,
            branch=branch,
            base=self.settings.git_branch,
            url="https://github.com/o/r/pull/9",
            number=9,
        )


def setup_function() -> None:
    FakeGitRepository.committed_messages = []
    FakeGitRepository.pushed_from = []
    FakeGitRepository.pushed_branches = []
    FakeGitRepository.created_prs = []


def test_kiro_runner_does_not_pass_github_token_to_kiro(monkeypatch, tmp_path) -> None:
    workflow = tmp_path / ".kiro" / "workflows" / "capture-text.md"
    request = tmp_path / ".content-archiver" / "incoming" / "request.yml"
    workflow.parent.mkdir(parents=True)
    request.parent.mkdir(parents=True)
    workflow.write_text("workflow", encoding="utf-8")
    request.write_text("id: test\n", encoding="utf-8")
    captured_env = {}
    captured_args = []

    def fake_run(args, **kwargs):
        captured_args.extend(args)
        captured_env.update(kwargs["env"])
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {"ok": True, "message": "done", "capture_id": "aws-london"}
            ),
            stderr="",
        )

    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_secret")
    monkeypatch.setattr("content_archiver_telegram.kiro_runner.subprocess.run", fake_run)
    monkeypatch.setattr(
        "content_archiver_telegram.kiro_runner.GitRepository",
        FakeGitRepository,
    )
    settings = Settings(
        content_repo_path=tmp_path,
        kiro_cli="kiro-cli",
        kiro_api_key="kiro-secret",
        github_token="github_pat_secret",
    )

    result = KiroRunner(settings).run_workflow(workflow_path=workflow, request_path=request)

    assert result["message"].startswith("done")
    assert captured_env["KIRO_API_KEY"] == "kiro-secret"
    assert "GITHUB_TOKEN" not in captured_env
    assert "--require-mcp-startup" in captured_args
    assert FakeGitRepository.committed_messages == ["capture: add aws-london text"]


def test_kiro_runner_can_disable_required_mcp_startup(monkeypatch, tmp_path) -> None:
    workflow = tmp_path / ".kiro" / "workflows" / "capture-image.md"
    request = tmp_path / ".content-archiver" / "incoming" / "request.yml"
    workflow.parent.mkdir(parents=True)
    request.parent.mkdir(parents=True)
    workflow.write_text("workflow", encoding="utf-8")
    request.write_text("id: test\n", encoding="utf-8")
    captured_args = []

    def fake_run(args, **kwargs):
        captured_args.extend(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {"ok": True, "message": "done", "capture_id": "aws-london"}
            ),
            stderr="",
        )

    monkeypatch.setattr("content_archiver_telegram.kiro_runner.subprocess.run", fake_run)
    monkeypatch.setattr(
        "content_archiver_telegram.kiro_runner.GitRepository",
        FakeGitRepository,
    )
    settings = Settings(
        content_repo_path=tmp_path,
        kiro_cli="kiro-cli",
        kiro_require_mcp_startup=False,
    )

    result = KiroRunner(settings).run_workflow(workflow_path=workflow, request_path=request)

    assert result["git_commit"]["committed"] is True
    assert "--require-mcp-startup" not in captured_args
    assert FakeGitRepository.committed_messages == ["capture: add aws-london image"]


def test_kiro_runner_creates_pull_request_in_pr_mode(monkeypatch, tmp_path) -> None:
    workflow = tmp_path / ".kiro" / "workflows" / "capture-video.md"
    request = tmp_path / ".content-archiver" / "incoming" / "telegram-9" / "request.yml"
    workflow.parent.mkdir(parents=True)
    request.parent.mkdir(parents=True)
    workflow.write_text("workflow", encoding="utf-8")
    request.write_text("id: telegram-9\n", encoding="utf-8")

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "message": "captured",
                    "capture_id": "aws-london",
                    "paths": ["captures/aws-london/capture.md"],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("content_archiver_telegram.kiro_runner.subprocess.run", fake_run)
    monkeypatch.setattr(
        "content_archiver_telegram.kiro_runner.GitRepository",
        FakeGitRepository,
    )
    settings = Settings(
        content_repo_path=tmp_path,
        kiro_cli="kiro-cli",
        capture_delivery_mode="pull-request",
        git_capture_branch="capture/telegram-9",
        github_token="token",
    )

    result = KiroRunner(settings).run_workflow(workflow_path=workflow, request_path=request)

    assert result["git_pr"]["url"] == "https://github.com/o/r/pull/9"
    assert FakeGitRepository.pushed_branches == ["capture/telegram-9"]
    assert FakeGitRepository.created_prs[0][0] == "capture/telegram-9"
    assert FakeGitRepository.created_prs[0][1] == "Capture aws-london from telegram-9"
