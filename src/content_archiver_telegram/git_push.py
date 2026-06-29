from __future__ import annotations

import base64
import subprocess
from dataclasses import dataclass

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


@dataclass(slots=True)
class GitRepository:
    settings: Settings

    def current_head(self) -> str | None:
        completed = self._git("rev-parse", "--verify", "HEAD", check=False)
        if completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

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

    def _git(self, *args: str, check: bool) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.settings.content_repo_path,
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
            raise GitPushError("GITHUB_TOKEN is required when GIT_PUSH=true.")
        credential = f"{self.settings.github_username}:{token}".encode("utf-8")
        encoded = base64.b64encode(credential).decode("ascii")
        return f"AUTHORIZATION: Basic {encoded}"


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


def _redact(text: str, settings: Settings) -> str:
    redacted = text
    if settings.github_token:
        redacted = redacted.replace(settings.github_token, "***")
    return redacted


def _safe_arg(arg: str) -> str:
    if "http.https://github.com/.extraheader=" in arg:
        return "http.https://github.com/.extraheader=***"
    return arg
