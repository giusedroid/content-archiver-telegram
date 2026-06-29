from __future__ import annotations

from typing import Any

from . import mcp_tools


def build_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "The `mcp` package is required to run content-archiver-mcp. "
            "Install this package with `uv sync`."
        ) from exc

    server = FastMCP("content-archiver-tools")

    @server.tool()
    def upload_original_to_s3(
        local_path: str,
        capture_id: str,
        asset_id: str,
        original_filename: str,
    ) -> dict[str, str]:
        """Upload an original local file to S3 and return its URI."""

        return mcp_tools.upload_original_to_s3(
            local_path=local_path,
            capture_id=capture_id,
            asset_id=asset_id,
            original_filename=original_filename,
        )

    @server.tool()
    def resize_image(input_path: str, output_path: str, max_width: int = 1280) -> dict[str, str]:
        """Create a low-resolution image preview suitable for Git."""

        return mcp_tools.resize_image(
            input_path=input_path,
            output_path=output_path,
            max_width=max_width,
        )

    @server.tool()
    def extract_video_frames(
        video_path: str,
        output_dir: str,
        count: int = 2,
    ) -> dict[str, list[str]]:
        """Extract representative video frames suitable for Git previews."""

        return mcp_tools.extract_video_frames(
            video_path=video_path,
            output_dir=output_dir,
            count=count,
        )

    @server.tool()
    def extract_audio(video_path: str, output_path: str) -> dict[str, str]:
        """Extract an audio track from a video."""

        return mcp_tools.extract_audio(video_path=video_path, output_path=output_path)

    @server.tool()
    def transcribe_audio(audio_path: str) -> dict[str, str]:
        """Transcribe an audio file using the configured transcription provider."""

        return mcp_tools.transcribe_audio(audio_path=audio_path)

    @server.tool()
    def pdf_to_markdown(pdf_path: str, output_path: str) -> dict[str, str]:
        """Convert a PDF to markdown."""

        return mcp_tools.pdf_to_markdown(pdf_path=pdf_path, output_path=output_path)

    @server.tool()
    def crawl_url_to_markdown(url: str, output_path: str) -> dict[str, str]:
        """Fetch a URL and store useful page content as markdown."""

        return mcp_tools.crawl_url_to_markdown(url=url, output_path=output_path)

    @server.tool()
    def index_lancedb(paths: list[str] | None = None) -> dict[str, Any]:
        """Index changed markdown into LanceDB or the local fallback index."""

        return mcp_tools.index_lancedb(paths=paths)

    @server.tool()
    def semantic_search(
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Search the content archive semantic memory."""

        return mcp_tools.semantic_search(query=query, limit=limit, filters=filters)

    return server


def main() -> None:
    build_server().run()
