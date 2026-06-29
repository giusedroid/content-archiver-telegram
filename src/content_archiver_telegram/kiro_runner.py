from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .git_push import GitRepository, attach_commit_result, attach_push_result


class KiroRunError(RuntimeError):
    pass


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
        output = self._run(prompt)
        result = _parse_json_output(output)
        commit = git.commit_all_if_changed(
            message=_commit_message(
                result=result,
                request_path=request_path,
                workflow_path=workflow_path,
            )
        )
        result = attach_commit_result(result, commit)
        if self.settings.git_push:
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
        output = self._run(prompt)
        return _parse_json_output(output)

    def _run(self, prompt: str) -> str:
        env = os.environ.copy()
        if self.settings.kiro_api_key:
            env["KIRO_API_KEY"] = self.settings.kiro_api_key
        env.pop("GITHUB_TOKEN", None)
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"

        args = [
            self.settings.kiro_cli or "kiro-cli",
            "chat",
            "--no-interactive",
            f"--trust-tools={self.settings.kiro_trust_tools}",
        ]
        if self.settings.kiro_require_mcp_startup:
            args.append("--require-mcp-startup")
        args.append(prompt)
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
        if completed.returncode != 0:
            raise KiroRunError(
                _redact(f"Kiro failed with exit {completed.returncode}:\n{output}", self.settings)
            )
        return _redact(output, self.settings)


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
        "Behave like Kiro IDE opened at the content repo root. Use repo files, .kiro "
        "steering, and configured MCP tools. Edit files directly when appropriate.\n\n"
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
