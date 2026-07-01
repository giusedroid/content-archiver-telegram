from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from content_archiver_telegram.config import Settings
from content_archiver_telegram.mcp_client import StdioMCPClient


def test_stdio_mcp_client_calls_tool(monkeypatch, tmp_path) -> None:
    real_popen = subprocess.Popen
    server = tmp_path / "fake_mcp.py"
    server.write_text(
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}}
    elif method == "tools/call":
        result = {"structuredContent": {"ok": request["params"]["arguments"]["value"]}, "isError": False}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
""".strip(),
        encoding="utf-8",
    )

    def fake_popen(args, **kwargs):
        assert args[:3] == ["uv", "run", "--project"]
        return real_popen(
            [sys.executable, str(server)],
            stdin=kwargs["stdin"],
            stdout=kwargs["stdout"],
            stderr=kwargs["stderr"],
            text=kwargs["text"],
            bufsize=kwargs["bufsize"],
        )

    monkeypatch.setattr("content_archiver_telegram.mcp_client.subprocess.Popen", fake_popen)

    with StdioMCPClient(Settings(content_repo_path=tmp_path)) as client:
        assert client.call_tool("demo", {"value": "yes"}) == {"ok": "yes"}
