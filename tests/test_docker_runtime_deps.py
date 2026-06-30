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
    assert 'export PATH="$CONTENT_REPO_PATH/tools/.venv/bin:$PATH"' in entrypoint


def test_dockerfile_does_not_force_runtime_bytecode_compilation() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "UV_COMPILE_BYTECODE=1" not in dockerfile


def test_docker_entrypoint_can_clone_archive_repo() -> None:
    entrypoint = Path("docker/entrypoint.sh").read_text(encoding="utf-8")

    assert "CONTENT_REPO_MODE:=clone" in entrypoint
    assert "CONTENT_REPO_GIT_URL is required" in entrypoint
    assert "run_git clone" in entrypoint
    assert "run_git -C \"$CONTENT_REPO_PATH\" fetch" in entrypoint
    assert "reset --hard" in entrypoint
    assert "extraheader=AUTHORIZATION: Basic" in entrypoint


def test_docker_compose_uses_named_content_repo_volume() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "source: content-repo" in compose
    assert "CONTENT_REPO_GIT_URL" in compose
    assert "CONTENT_REPO_HOST_PATH" not in compose


def test_docker_entrypoint_normalizes_git_status_for_runtime_checkout() -> None:
    entrypoint = Path("docker/entrypoint.sh").read_text(encoding="utf-8")

    assert 'git -C "$CONTENT_REPO_PATH" config core.autocrlf input' in entrypoint
    assert 'git -C "$CONTENT_REPO_PATH" config core.filemode false' in entrypoint
