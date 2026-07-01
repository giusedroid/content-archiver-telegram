from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Settings


class GitPushError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GitPushResult:
    enabled: bool
    pushed: bool
    remote: str
    branch: str
    before_head: str | None
    after_head: str | None


@dataclass(frozen=True, slots=True)
class GitCommitResult:
    changed: bool
    committed: bool
    before_head: str | None
    after_head: str | None
    message: str | None


@dataclass(frozen=True, slots=True)
class GitPullRequestResult:
    enabled: bool
    pushed: bool
    created: bool
    branch: str
    base: str
    url: str | None
    number: int | None


@dataclass(slots=True)
class GitRepository:
    settings: Settings
    repo_path: Path | None = None

    @property
    def path(self) -> Path:
        return self.repo_path or self.settings.content_repo_path

    def current_head(self) -> str | None:
        completed = self._git("rev-parse", "--verify", "HEAD", check=False)
        if completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

    def has_changes(self) -> bool:
        completed = self._git("status", "--porcelain", check=True)
        return bool(completed.stdout.strip())

    def assert_clean_for_capture(self) -> None:
        if self.has_changes():
            raise GitPushError(
                "Content repository has uncommitted changes. Commit, push, or clean the "
                "content repo before processing another capture."
            )

    def create_capture_worktree(self, *, request_id: str) -> tuple[Path, str]:
        branch = request_branch_name(self.settings.git_branch_prefix, request_id)
        worktree_path = self.settings.git_worktree_root / safe_path_name(request_id)
        if worktree_path.exists():
            raise GitPushError(f"Capture worktree already exists: {worktree_path}")
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        self._git(
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            self.settings.git_branch,
            check=True,
        )
        self._link_archive_tools_venv(worktree_path)
        return worktree_path, branch

    def _link_archive_tools_venv(self, worktree_path: Path) -> None:
        source = self.settings.content_repo_path / "tools" / ".venv"
        target = worktree_path / "tools" / ".venv"
        if not source.exists() or not target.parent.exists():
            return
        if target.exists() or target.is_symlink():
            if target.resolve() == source.resolve():
                return
            raise GitPushError(f"Archive tools venv already exists in capture worktree: {target}")
        try:
            os.symlink(source, target, target_is_directory=True)
        except OSError as exc:
            raise GitPushError(
                "Failed to link archive tools venv into capture worktree. "
                f"Source: {source}. Target: {target}."
            ) from exc

    def commit_all_if_changed(self, *, message: str) -> GitCommitResult:
        before_head = self.current_head()
        if not self.has_changes():
            return GitCommitResult(
                changed=False,
                committed=False,
                before_head=before_head,
                after_head=before_head,
                message=None,
            )

        self._git("add", "-A", check=True)
        self._git("commit", "-m", message, check=True)
        return GitCommitResult(
            changed=True,
            committed=True,
            before_head=before_head,
            after_head=self.current_head(),
            message=message,
        )

    def push_if_head_changed(self, *, before_head: str | None) -> GitPushResult:
        if not self.settings.git_push:
            return GitPushResult(
                enabled=False,
                pushed=False,
                remote=self.settings.git_remote,
                branch=self.settings.git_branch,
                before_head=before_head,
                after_head=self.current_head(),
            )

        self.settings.validate_git_push()
        after_head = self.current_head()
        if after_head == before_head:
            return GitPushResult(
                enabled=True,
                pushed=False,
                remote=self.settings.git_remote,
                branch=self.settings.git_branch,
                before_head=before_head,
                after_head=after_head,
            )

        self._git(
            "-c",
            f"http.https://github.com/.extraheader={self._github_auth_header()}",
            "push",
            self.settings.git_remote,
            f"HEAD:{self.settings.git_branch}",
            check=True,
        )
        return GitPushResult(
            enabled=True,
            pushed=True,
            remote=self.settings.git_remote,
            branch=self.settings.git_branch,
            before_head=before_head,
            after_head=after_head,
        )

    def push_branch(self, *, branch: str) -> None:
        self.settings.validate_delivery_mode()
        self._git(
            "-c",
            f"http.https://github.com/.extraheader={self._github_auth_header()}",
            "push",
            self.settings.git_remote,
            f"HEAD:refs/heads/{branch}",
            check=True,
        )

    def create_pull_request(
        self,
        *,
        branch: str,
        title: str,
        body: str,
    ) -> GitPullRequestResult:
        self.settings.validate_delivery_mode()
        repo = self._github_repo_slug()
        payload = {
            "title": title,
            "head": branch,
            "base": self.settings.git_branch,
            "body": body,
        }
        data = self._github_json_request(
            "POST",
            f"/repos/{repo}/pulls",
            payload=payload,
        )
        return GitPullRequestResult(
            enabled=True,
            pushed=True,
            created=True,
            branch=branch,
            base=self.settings.git_branch,
            url=data.get("html_url"),
            number=data.get("number"),
        )

    def find_pull_request_for_branch(self, *, branch: str) -> GitPullRequestResult:
        self.settings.validate_delivery_mode()
        repo = self._github_repo_slug()
        owner = repo.split("/", 1)[0]
        query = urlencode({"head": f"{owner}:{branch}", "state": "all"})
        data = self._github_json_request("GET", f"/repos/{repo}/pulls?{query}")
        if not isinstance(data, list) or not data:
            return GitPullRequestResult(
                enabled=True,
                pushed=True,
                created=False,
                branch=branch,
                base=self.settings.git_branch,
                url=None,
                number=None,
            )
        pr = data[0]
        return GitPullRequestResult(
            enabled=True,
            pushed=True,
            created=True,
            branch=branch,
            base=self.settings.git_branch,
            url=pr.get("html_url"),
            number=pr.get("number"),
        )

    def _git(self, *args: str, check: bool) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.path,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and completed.returncode != 0:
            output = (completed.stdout or "") + (completed.stderr or "")
            command = "git " + " ".join(_safe_arg(arg) for arg in args)
            raise GitPushError(_redact(f"Git command failed: {command}\n{output}", self.settings))
        return completed

    def _github_auth_header(self) -> str:
        token = self.settings.github_token
        if not token:
            raise GitPushError("GITHUB_TOKEN is required for authenticated git operations.")
        credential = f"{self.settings.github_username}:{token}".encode("utf-8")
        encoded = base64.b64encode(credential).decode("ascii")
        return f"AUTHORIZATION: Basic {encoded}"

    def _github_repo_slug(self) -> str:
        if self.settings.github_repository:
            return self.settings.github_repository.removesuffix(".git")
        completed = self._git("remote", "get-url", self.settings.git_remote, check=True)
        remote_url = completed.stdout.strip()
        patterns = [
            r"github\.com[:/](?P<repo>[^/\s]+/[^/\s]+?)(?:\.git)?$",
            r"^https?://[^/]+/(?P<repo>[^/\s]+/[^/\s]+?)(?:\.git)?$",
        ]
        for pattern in patterns:
            match = re.search(pattern, remote_url)
            if match:
                return match.group("repo")
        raise GitPushError(
            "Could not determine GitHub repository. Set GITHUB_REPOSITORY=owner/repo."
        )

    def _github_json_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        if not self.settings.github_token:
            raise GitPushError("GITHUB_TOKEN is required for GitHub API requests.")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.settings.github_api_base_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.settings.github_token}",
                "Content-Type": "application/json",
                "User-Agent": "content-archiver-telegram",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitPushError(
                _redact(f"GitHub API failed with HTTP {exc.code}: {detail}", self.settings)
            ) from exc
        except URLError as exc:
            raise GitPushError(_redact(f"GitHub API request failed: {exc}", self.settings)) from exc


def attach_commit_result(result: dict, commit: GitCommitResult) -> dict:
    result["git_commit"] = {
        "changed": commit.changed,
        "committed": commit.committed,
        "before_head": commit.before_head,
        "after_head": commit.after_head,
        "message": commit.message,
    }
    if commit.committed and isinstance(result.get("message"), str):
        result["message"] = f"{result['message']} Committed as `{commit.message}`."
    return result


def attach_push_result(result: dict, push: GitPushResult) -> dict:
    result["git_push"] = {
        "enabled": push.enabled,
        "pushed": push.pushed,
        "remote": push.remote,
        "branch": push.branch,
        "before_head": push.before_head,
        "after_head": push.after_head,
    }
    if push.pushed and isinstance(result.get("message"), str):
        result["message"] = f"{result['message']} Pushed to {push.remote}/{push.branch}."
    return result


def attach_pull_request_result(result: dict, pull_request: GitPullRequestResult) -> dict:
    result["git_pr"] = {
        "enabled": pull_request.enabled,
        "pushed": pull_request.pushed,
        "created": pull_request.created,
        "branch": pull_request.branch,
        "base": pull_request.base,
        "url": pull_request.url,
        "number": pull_request.number,
    }
    if pull_request.url and isinstance(result.get("message"), str):
        result["message"] = f"{result['message']} PR: {pull_request.url}"
    return result


def request_branch_name(prefix: str, request_id: str) -> str:
    return f"{safe_path_name(prefix)}/{safe_path_name(request_id)}"


def safe_path_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return re.sub(r"-+", "-", cleaned).strip("-") or "request"


def _redact(text: str, settings: Settings) -> str:
    redacted = text
    if settings.github_token:
        redacted = redacted.replace(settings.github_token, "***")
        encoded = base64.b64encode(f"{settings.github_username}:{settings.github_token}".encode()).decode(
            "ascii"
        )
        redacted = redacted.replace(encoded, "***")
    return redacted


def _safe_arg(arg: str) -> str:
    if "http.https://github.com/.extraheader=" in arg:
        return "http.https://github.com/.extraheader=***"
    return arg
