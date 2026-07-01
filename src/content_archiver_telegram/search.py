from __future__ import annotations

import re
import subprocess
from typing import Any

from .config import Settings
from .mcp_client import StdioMCPClient


def index_archive(settings: Settings) -> dict[str, Any]:
    with StdioMCPClient(settings) as client:
        return client.call_tool("index_lancedb", {})


def search_archive(settings: Settings, *, query: str, limit: int = 10) -> dict[str, Any]:
    try:
        with StdioMCPClient(settings) as client:
            index_result = client.call_tool("index_lancedb", {})
            search_result = client.call_tool(
                "semantic_search",
                {
                    "query": query,
                    "limit": limit,
                },
            )
    finally:
        cleanup_generated_index_artifacts(settings)
    return {
        "ok": True,
        "query": query,
        "index": index_result,
        "results": search_result.get("results", []),
        "github_repository": settings.github_repository,
        "git_branch": settings.git_branch,
    }


def format_search_result(result: dict[str, Any]) -> str:
    results = result.get("results") if isinstance(result.get("results"), list) else []
    index = result.get("index") if isinstance(result.get("index"), dict) else {}
    if not results:
        return (
            f"No matches for `{result.get('query', '')}`.\n"
            f"Index scanned {index.get('scanned_files', 0)} files."
        )

    groups = _group_results_by_capture(results)
    shown_groups = groups[:3]
    lines = [
        f"Found {len(groups)} relevant capture(s) for `{result.get('query', '')}`.",
        (
            f"Index scanned {index.get('scanned_files', 0)} files; "
            f"{index.get('changed_files', 0)} changed."
        ),
    ]
    for index, group in enumerate(shown_groups, start=1):
        item = group["best"]
        capture_id = str(group["capture_id"])
        title = _title_from_capture_id(capture_id)
        path = str(item.get("path") or f"captures/{capture_id}/capture.md")
        snippet = _snippet(str(item.get("content") or ""))
        strength = _match_strength(item, group["rank"])
        capture_url = _github_url(
            result,
            f"captures/{capture_id}/capture.md",
            None,
            None,
        )
        match_url = _github_url(
            result,
            path,
            _int_or_none(item.get("start_line")),
            _int_or_none(item.get("end_line")),
        )
        lines.append(
            "\n".join(
                [
                    f"{index}. {title}",
                    f"   {strength}. Best match: `{path}`",
                    f"   \"{snippet}\"",
                    f"   Open capture: {capture_url}" if capture_url else "",
                    f"   Open matched file: {match_url}" if match_url else "",
                ]
            ).strip()
        )
    if len(groups) > len(shown_groups):
        lines.append(f"Showing top {len(shown_groups)} captures from {len(results)} matching chunks.")
    return "\n".join(lines)


def cleanup_generated_index_artifacts(settings: Settings) -> None:
    generated_paths = [
        "index/lancedb-manifest.yml",
        "index/index-report.json",
        "index/semantic-records.jsonl",
    ]
    repo_path = settings.content_repo_path
    for path in generated_paths:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), "ls-files", "--error-unmatch", path],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode == 0:
            subprocess.run(
                ["git", "-C", str(repo_path), "checkout", "--", path],
                text=True,
                capture_output=True,
                check=False,
            )
            continue
        target = repo_path / path
        if target.exists():
            target.unlink()


def _group_results_by_capture(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    by_capture: dict[str, dict[str, Any]] = {}
    for rank, item in enumerate(results):
        capture_id = str(item.get("capture_id") or "unknown")
        group = by_capture.get(capture_id)
        if group is None:
            group = {"capture_id": capture_id, "best": item, "rank": rank, "matches": []}
            by_capture[capture_id] = group
            groups.append(group)
        group["matches"].append(item)
        if _result_sort_key(item, rank) < _result_sort_key(group["best"], group["rank"]):
            group["best"] = item
            group["rank"] = rank
    groups.sort(key=lambda group: _result_sort_key(group["best"], group["rank"]))
    return groups


def _result_sort_key(item: dict[str, Any], rank: int) -> tuple[float, int]:
    if item.get("score") is not None:
        return (-float(item["score"]), rank)
    if item.get("_distance") is not None:
        return (float(item["_distance"]), rank)
    return (float(rank), rank)


def _match_strength(item: dict[str, Any], rank: int) -> str:
    score = item.get("score")
    if score is not None:
        score_value = float(score)
        if score_value >= 0.67:
            return "Strong match"
        if score_value >= 0.34:
            return "Likely match"
        return "Weak match"
    if item.get("_distance") is not None:
        return f"Semantic match #{rank + 1}"
    return f"Match #{rank + 1}"


def _github_url(
    result: dict[str, Any],
    path: str,
    start_line: int | None,
    end_line: int | None,
) -> str | None:
    repository = str(result.get("github_repository") or "").strip().strip("/")
    branch = str(result.get("git_branch") or "main").strip() or "main"
    if not repository or "/" not in repository:
        return None
    safe_path = "/".join(part for part in path.replace("\\", "/").split("/") if part)
    url = f"https://github.com/{repository}/blob/{branch}/{safe_path}"
    if start_line and end_line and end_line >= start_line:
        url += f"#L{start_line}-L{end_line}"
    elif start_line:
        url += f"#L{start_line}"
    return url


def _snippet(content: str, max_chars: int = 220) -> str:
    compact = re.sub(r"\s+", " ", content).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _title_from_capture_id(capture_id: str) -> str:
    return " ".join(part.capitalize() for part in capture_id.split("-") if part) or capture_id


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
