from __future__ import annotations

from typing import Any

from .config import Settings
from .mcp_client import StdioMCPClient


def index_archive(settings: Settings) -> dict[str, Any]:
    with StdioMCPClient(settings) as client:
        return client.call_tool("index_lancedb", {})


def search_archive(settings: Settings, *, query: str, limit: int = 10) -> dict[str, Any]:
    with StdioMCPClient(settings) as client:
        index_result = client.call_tool("index_lancedb", {})
        search_result = client.call_tool(
            "semantic_search",
            {
                "query": query,
                "limit": limit,
            },
        )
    return {
        "ok": True,
        "query": query,
        "index": index_result,
        "results": search_result.get("results", []),
    }


def format_search_result(result: dict[str, Any]) -> str:
    results = result.get("results") if isinstance(result.get("results"), list) else []
    index = result.get("index") if isinstance(result.get("index"), dict) else {}
    if not results:
        return (
            f"No matches for `{result.get('query', '')}`.\n"
            f"Index scanned {index.get('scanned_files', 0)} files."
        )

    lines = [
        f"Found {len(results)} match(es) for `{result.get('query', '')}`.",
        (
            f"Index scanned {index.get('scanned_files', 0)} files; "
            f"{index.get('changed_files', 0)} changed."
        ),
    ]
    for item in results[:10]:
        path = item.get("path") or "unknown"
        capture_id = item.get("capture_id") or "unknown"
        score = item.get("score")
        score_text = f" score {score}" if score is not None else ""
        content = str(item.get("content") or "").replace("\n", " ").strip()
        snippet = content[:220] + ("..." if len(content) > 220 else "")
        lines.append(f"- `{capture_id}` `{path}`{score_text}\n  {snippet}")
    return "\n".join(lines)
