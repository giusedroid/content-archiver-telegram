from __future__ import annotations

import subprocess

from content_archiver_telegram.config import Settings
from content_archiver_telegram.search import (
    cleanup_generated_index_artifacts,
    format_search_result,
    index_archive,
    search_archive,
)


class FakeMCPClient:
    calls: list[tuple[str, dict]] = []

    def __init__(self, settings):
        self.settings = settings

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        if name == "index_lancedb":
            return {"scanned_files": 2, "changed_files": 1, "chunks": 3}
        if name == "semantic_search":
            return {
                "results": [
                    {
                        "score": 0.75,
                        "capture_id": "aws-london-summit",
                        "path": "captures/aws-london-summit/capture.md",
                        "start_line": 4,
                        "end_line": 5,
                        "content": "Interview notes with Jeff Barr.",
                    }
                ]
            }
        raise AssertionError(name)


def test_index_archive_calls_mcp(monkeypatch, tmp_path) -> None:
    FakeMCPClient.calls = []
    monkeypatch.setattr("content_archiver_telegram.search.StdioMCPClient", FakeMCPClient)

    result = index_archive(Settings(content_repo_path=tmp_path))

    assert result["scanned_files"] == 2
    assert FakeMCPClient.calls == [("index_lancedb", {})]


def test_search_archive_indexes_then_searches(monkeypatch, tmp_path) -> None:
    FakeMCPClient.calls = []
    monkeypatch.setattr("content_archiver_telegram.search.StdioMCPClient", FakeMCPClient)

    settings = Settings(
        content_repo_path=tmp_path,
        github_repository="giusedroid/content-archive-repo",
        git_branch="main",
    )

    result = search_archive(settings, query="Jeff Barr", limit=5)

    assert result["ok"] is True
    assert result["results"][0]["capture_id"] == "aws-london-summit"
    assert result["github_repository"] == "giusedroid/content-archive-repo"
    assert FakeMCPClient.calls == [
        ("index_lancedb", {}),
        ("semantic_search", {"query": "Jeff Barr", "limit": 5}),
    ]


def test_format_search_result() -> None:
    message = format_search_result(
        {
            "query": "Jeff Barr",
            "index": {"scanned_files": 2, "changed_files": 1},
            "github_repository": "giusedroid/content-archive-repo",
            "git_branch": "main",
            "results": [
                {
                    "score": 0.75,
                    "capture_id": "aws-london-summit",
                    "path": "captures/aws-london-summit/capture.md",
                    "start_line": 4,
                    "end_line": 5,
                    "content": "Interview notes with Jeff Barr.",
                },
                {
                    "score": 0.5,
                    "capture_id": "aws-london-summit",
                    "path": "captures/aws-london-summit/assets.md",
                    "start_line": 1,
                    "end_line": 2,
                    "content": "Another chunk from the same capture.",
                }
            ],
        }
    )

    assert "Found 1 relevant capture" in message
    assert "Aws London Summit" in message
    assert "Open capture: https://github.com/giusedroid/content-archive-repo/blob/main/captures/aws-london-summit/capture.md" in message
    assert "Open matched file: https://github.com/giusedroid/content-archive-repo/blob/main/captures/aws-london-summit/capture.md#L4-L5" in message
    assert "Another chunk" not in message


def test_cleanup_generated_index_artifacts_restores_repo(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    manifest = index_dir / "lancedb-manifest.yml"
    manifest.write_text("version: 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "index/lancedb-manifest.yml"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    manifest.write_text("version: 2\n", encoding="utf-8")
    (index_dir / "index-report.json").write_text("{}", encoding="utf-8")
    (index_dir / "semantic-records.jsonl").write_text("{}", encoding="utf-8")

    cleanup_generated_index_artifacts(Settings(content_repo_path=tmp_path))

    assert manifest.read_text(encoding="utf-8") == "version: 1\n"
    assert not (index_dir / "index-report.json").exists()
    assert not (index_dir / "semantic-records.jsonl").exists()
