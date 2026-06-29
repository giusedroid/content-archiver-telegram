from __future__ import annotations

import tomllib
from pathlib import Path


def test_docker_image_project_installs_archive_tool_dependencies() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependency_names = {
        requirement.split(">=", 1)[0].split("==", 1)[0]
        for requirement in pyproject["project"]["dependencies"]
    }

    assert {
        "boto3",
        "lancedb",
        "markitdown",
        "mcp",
        "openai",
        "pillow",
        "pyyaml",
        "requests",
    } <= dependency_names
