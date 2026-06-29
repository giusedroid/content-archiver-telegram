import builtins

import pytest

from content_archiver_telegram import mcp_server


def test_mcp_server_reports_missing_mcp_dependency(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mcp.server.fastmcp":
            raise ImportError("missing mcp")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="mcp"):
        mcp_server.build_server()
