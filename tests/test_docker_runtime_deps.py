from __future__ import annotations

import tomllib
from pathlib import Path


def test_telegram_package_does_not_own_archive_tool_dependencies() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependency_names = {
        requirement.split(">=", 1)[0].split("==", 1)[0]
        for requirement in pyproject["project"]["dependencies"]
    }

    assert not {
        "boto3",
        "lancedb",
        "markitdown",
        "mcp",
        "openai",
        "pillow",
        "requests",
    } & dependency_names


def test_docker_entrypoint_syncs_archive_tools_project() -> None:
    entrypoint = Path("docker/entrypoint.sh").read_text(encoding="utf-8")

    assert 'uv sync --project "$CONTENT_REPO_PATH/tools"' in entrypoint
    assert "ARCHIVE_TOOLS_SYNC" in entrypoint
