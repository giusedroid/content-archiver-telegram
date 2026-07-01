from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings


class MCPClientError(RuntimeError):
    pass


@dataclass(slots=True)
class StdioMCPClient:
    settings: Settings
    _process: subprocess.Popen[str] | None = None
    _stdout: queue.Queue[str] = field(default_factory=queue.Queue)
    _stderr: list[str] = field(default_factory=list)
    _next_id: int = 1

    def __enter__(self) -> "StdioMCPClient":
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return
        env = os.environ.copy()
        env["CONTENT_REPO_PATH"] = str(self.settings.content_repo_path)
        self._process = subprocess.Popen(
            ["uv", "run", "--project", "tools", "content-archive-mcp"],
            cwd=self.settings.content_repo_path,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
        self.notify("notifications/initialized", {})

    def close(self) -> None:
        if self._process is None:
            return
        if self._process.stdin:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=5)
        self._process = None

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        result = response.get("result") or {}
        if result.get("isError"):
            text = result.get("content", [{}])[0].get("text", "MCP tool failed")
            raise MCPClientError(str(text))
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content") or []
        if content and isinstance(content[0], dict):
            return json.loads(str(content[0].get("text") or "{}"))
        return {}

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = self.settings.archive_mcp_timeout_seconds
        while True:
            try:
                line = self._stdout.get(timeout=deadline)
            except queue.Empty as exc:
                raise MCPClientError(
                    f"MCP server timed out during {method}. Stderr: {self.stderr_tail()}"
                ) from exc
            response = json.loads(line)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                message = response["error"].get("message", response["error"])
                raise MCPClientError(f"MCP {method} failed: {message}")
            return response

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def stderr_tail(self, max_chars: int = 4000) -> str:
        text = "".join(self._stderr)
        return text[-max_chars:]

    def _send(self, payload: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise MCPClientError("MCP server is not running.")
        self._process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._process.stdin.flush()

    def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        for line in self._process.stdout:
            if line.strip():
                self._stdout.put(line.strip())

    def _read_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        for line in self._process.stderr:
            self._stderr.append(line)


def request_dir_from_request_path(request_path: Path) -> Path:
    return request_path.parent
