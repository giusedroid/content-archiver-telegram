from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .git_push import (
    GitPullRequestResult,
    GitRepository,
    attach_commit_result,
    attach_pull_request_result,
    attach_push_result,
    request_branch_name,
)


class KiroRunError(RuntimeError):
    pass


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class KiroRunner:
    settings: Settings

    def run_workflow(self, *, workflow_path: Path, request_path: Path) -> dict[str, Any]:
        self.settings.validate_kiro()
        workflow_text = workflow_path.read_text(encoding="utf-8")
        prompt = _workflow_prompt(
            workflow_path=workflow_path,
            request_path=request_path,
            workflow_text=workflow_text,
            content_repo_path=self.settings.content_repo_path,
        )
        git = GitRepository(self.settings)
        before_head = git.current_head()
        output = self._run(prompt, run_label=request_path.parent.name)
        result = _parse_json_output(output)
        result["_kiro_log"] = output
        commit = git.commit_all_if_changed(
            message=_commit_message(
                result=result,
                request_path=request_path,
                workflow_path=workflow_path,
            )
        )
        result = attach_commit_result(result, commit)
        if self.settings.uses_pull_requests:
            branch = self.settings.git_capture_branch or request_branch_name(
                self.settings.git_branch_prefix,
                request_path.parent.name,
            )
            pull_request = _create_pull_request(
                git=git,
                result=result,
                request_path=request_path,
                branch=branch,
                commit_created=commit.committed,
            )
            result = attach_pull_request_result(result, pull_request)
        elif self.settings.git_push:
            push = git.push_if_head_changed(before_head=before_head)
            result = attach_push_result(result, push)
        return result

    def run_search(self, *, query: str) -> dict[str, Any]:
        self.settings.validate_kiro()
        workflow_path = self.settings.content_repo_path / ".kiro" / "workflows" / "search.md"
        workflow_text = workflow_path.read_text(encoding="utf-8")
        prompt = (
            f"{workflow_text}\n\n"
            f"User search query:\n{query}\n\n"
            "Return only valid JSON for Telegram with keys ok, message, and results."
        )
        output = self._run(prompt, run_label="search")
        return _parse_json_output(output)

    def _run(self, prompt: str, *, run_label: str) -> str:
        env = os.environ.copy()
        if self.settings.kiro_api_key:
            env["KIRO_API_KEY"] = self.settings.kiro_api_key
        env.pop("GITHUB_TOKEN", None)
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"

        args = [
            self.settings.kiro_cli or "kiro-cli",
            "chat",
            *["-v" for _ in range(self.settings.kiro_verbose)],
            "--no-interactive",
            f"--trust-tools={self.settings.kiro_trust_tools}",
        ]
        if self.settings.kiro_require_mcp_startup:
            args.append("--require-mcp-startup")
        args.append(prompt)
        workspace_mcp = self.settings.content_repo_path / ".kiro" / "settings" / "mcp.json"
        global_mcp = Path(os.getenv("KIRO_GLOBAL_MCP_PATH", "/root/.kiro/settings/mcp.json"))
        LOGGER.info(
            "Starting Kiro run label=%s cwd=%s cli=%s verbose=%s require_mcp=%s "
            "trust_tool_count=%s workspace_mcp_exists=%s global_mcp=%s global_mcp_exists=%s "
            "prompt_chars=%s command=%s",
            run_label,
            self.settings.content_repo_path,
            self.settings.kiro_cli or "kiro-cli",
            self.settings.kiro_verbose,
            self.settings.kiro_require_mcp_startup,
            len([tool for tool in self.settings.kiro_trust_tools.split(",") if tool]),
            workspace_mcp.exists(),
            global_mcp,
            global_mcp.exists(),
            len(prompt),
            _safe_command(args),
        )
        try:
            completed = subprocess.run(
                args,
                cwd=self.settings.content_repo_path,
                env=env,
                text=True,
                capture_output=True,
                timeout=self.settings.kiro_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise KiroRunError("Kiro workflow timed out.") from exc
        except OSError as exc:
            raise KiroRunError(f"Failed to run Kiro CLI: {args[0]}") from exc

        output = (completed.stdout or "") + (completed.stderr or "")
        redacted_output = _redact(output, self.settings)
        log_path = _write_kiro_log(
            settings=self.settings,
            run_label=run_label,
            args=args,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        LOGGER.info(
            "Kiro run finished label=%s returncode=%s stdout_chars=%s stderr_chars=%s log_path=%s",
            run_label,
            completed.returncode,
            len(completed.stdout or ""),
            len(completed.stderr or ""),
            log_path,
        )
        if completed.returncode != 0:
            raise KiroRunError(
                f"Kiro failed with exit {completed.returncode}. "
                f"Redacted log: {log_path}\n{redacted_output}"
            )
        if self.settings.kiro_require_mcp_startup and _mcp_startup_failed(output):
            LOGGER.warning(
                "Kiro MCP startup failed label=%s log_path=%s output_tail=%s",
                run_label,
                log_path,
                _tail(redacted_output, 12000),
            )
            raise KiroRunError(
                "Kiro completed without MCP tools mounted even though "
                "KIRO_REQUIRE_MCP_STARTUP=true. "
                f"Redacted log: {log_path}\n{redacted_output}"
            )
        return redacted_output


def _workflow_prompt(
    *,
    workflow_path: Path,
    request_path: Path,
    workflow_text: str,
    content_repo_path: Path,
) -> str:
    workflow_rel = workflow_path.relative_to(content_repo_path).as_posix()
    request_rel = request_path.relative_to(content_repo_path).as_posix()
    return (
        "You are Kiro headless operating inside this content archive repository.\n"
        "Behave like Kiro IDE opened at the content repo root. Use repo files and .kiro "
        "steering. The Telegram runtime has already executed deterministic archive MCP "
        "tooling and written results into the incoming request file. Do not try to call "
        "MCP tools, shell commands, or subagents. Edit files directly when appropriate.\n\n"
        f"Workflow file: {workflow_rel}\n"
        f"Incoming request file: {request_rel}\n\n"
        "Follow this workflow:\n\n"
        f"{workflow_text}\n\n"
        "When complete, return only valid JSON:\n"
        "{\n"
        '  "ok": true,\n'
        '  "message": "Telegram-friendly result.",\n'
        '  "capture_id": "optional-capture-id",\n'
        '  "paths": ["optional/path.md"]\n'
        "}\n"
    )


def _commit_message(
    *,
    result: dict[str, Any],
    request_path: Path,
    workflow_path: Path,
) -> str:
    capture_id = str(result.get("capture_id") or "").strip()
    media_type = _media_type_from_workflow(workflow_path)
    if capture_id:
        return f"capture: add {capture_id} {media_type}"
    return f"capture: add inbox item {request_path.parent.name}"


def _media_type_from_workflow(workflow_path: Path) -> str:
    name = workflow_path.stem
    if name.startswith("capture-"):
        return name.removeprefix("capture-")
    return "item"


def _create_pull_request(
    *,
    git: GitRepository,
    result: dict[str, Any],
    request_path: Path,
    branch: str,
    commit_created: bool,
) -> GitPullRequestResult:
    if not commit_created:
        return GitPullRequestResult(
            enabled=True,
            pushed=False,
            created=False,
            branch=branch,
            base=git.settings.git_branch,
            url=None,
            number=None,
        )
    git.push_branch(branch=branch)
    return git.create_pull_request(
        branch=branch,
        title=_pull_request_title(result=result, request_id=request_path.parent.name),
        body=_pull_request_body(result=result, request_path=request_path),
    )


def _pull_request_title(*, result: dict[str, Any], request_id: str) -> str:
    capture_id = str(result.get("capture_id") or "").strip()
    if capture_id:
        return f"Capture {capture_id} from {request_id}"
    return f"Capture inbox item {request_id}"


def _pull_request_body(*, result: dict[str, Any], request_path: Path) -> str:
    message = str(result.get("message") or "Kiro completed the capture workflow.")
    paths = result.get("paths") if isinstance(result.get("paths"), list) else []
    path_lines = "\n".join(f"- `{path}`" for path in paths) or "- No paths reported."
    kiro_log = str(result.get("_kiro_log") or "No Kiro output captured.")
    return (
        f"Request: `{request_path.parent.name}`\n\n"
        f"Kiro result:\n\n{message}\n\n"
        f"Reported paths:\n\n{path_lines}\n\n"
        f"Full Kiro log:\n\n```text\n{_fence_safe(kiro_log)}\n```\n"
    )


def _fence_safe(text: str) -> str:
    return text.replace("```", "`\u200b``")


def _mcp_startup_failed(output: str) -> bool:
    normalized = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    return (
        "Failed to retrieve MCP settings" in normalized
        or "MCP functionality disabled" in normalized
    )


def _write_kiro_log(
    *,
    settings: Settings,
    run_label: str,
    args: list[str],
    returncode: int,
    stdout: str,
    stderr: str,
) -> Path:
    settings.kiro_log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = settings.kiro_log_dir / f"{timestamp}-{_safe_label(run_label)}-{os.getpid()}.log"
    content = (
        f"cwd: {settings.content_repo_path}\n"
        f"returncode: {returncode}\n"
        f"command: {_safe_command(args)}\n"
        f"kiro_verbose: {settings.kiro_verbose}\n"
        f"require_mcp_startup: {settings.kiro_require_mcp_startup}\n"
        f"trust_tool_count: "
        f"{len([tool for tool in settings.kiro_trust_tools.split(',') if tool])}\n"
        f"workspace_mcp: {settings.content_repo_path / '.kiro' / 'settings' / 'mcp.json'}\n"
        f"global_mcp: {os.getenv('KIRO_GLOBAL_MCP_PATH', '/root/.kiro/settings/mcp.json')}\n"
        "\n--- stdout ---\n"
        f"{stdout}\n"
        "\n--- stderr ---\n"
        f"{stderr}\n"
    )
    path.write_text(_redact(content, settings), encoding="utf-8")
    return path


def _safe_command(args: list[str]) -> str:
    safe_args = [*args]
    if safe_args:
        safe_args[-1] = f"<prompt chars={len(safe_args[-1])}>"
    return " ".join(safe_args)


def _safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "kiro"


def _tail(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[-max_chars:]


def _parse_json_output(output: str) -> dict[str, Any]:
    cleaned = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(cleaned):
            if char != "{":
                continue
            try:
                data, _ = decoder.raw_decode(cleaned[index:])
                break
            except json.JSONDecodeError:
                continue
        else:
            raise KiroRunError("Kiro did not return valid JSON.")
    if not isinstance(data, dict):
        raise KiroRunError("Kiro JSON result must be an object.")
    return data


def _redact(text: str, settings: Settings) -> str:
    redacted = text
    if settings.kiro_api_key:
        redacted = redacted.replace(settings.kiro_api_key, "***")
    if settings.github_token:
        redacted = redacted.replace(settings.github_token, "***")
    return redacted
