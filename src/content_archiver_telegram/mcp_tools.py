from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class ToolSettings:
    content_repo_path: Path
    aws_profile: str | None = None
    aws_region: str | None = None
    s3_bucket: str | None = None
    s3_prefix: str = "raw/"
    s3_dry_run: bool = False
    transcription_provider: str = "amazon-transcribe"
    amazon_transcribe_language_code: str | None = None
    amazon_transcribe_identify_language: bool = True
    amazon_transcribe_input_prefix: str = "transcribe/input/"
    amazon_transcribe_output_prefix: str = "transcribe/output/"
    amazon_transcribe_poll_seconds: float = 5.0
    amazon_transcribe_timeout_seconds: int = 900
    openai_audio_base_url: str = "http://localhost:8000/v1"
    openai_audio_api_key: str = "cant-be-empty"
    whisper_model: str = "Systran/faster-distil-whisper-small.en"
    firecrawl_api_key: str | None = None
    lancedb_uri: str | None = None
    lancedb_table: str = "captures"
    embedding_provider: str = "stub"
    embedding_model: str = "text-embedding-3-small"
    openai_base_url: str | None = None
    openai_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "ToolSettings":
        return cls(
            content_repo_path=Path(os.getenv("CONTENT_REPO_PATH", ".")).resolve(),
            aws_profile=os.getenv("AWS_PROFILE") or None,
            aws_region=os.getenv("AWS_REGION") or None,
            s3_bucket=os.getenv("S3_BUCKET") or None,
            s3_prefix=os.getenv("S3_PREFIX", "raw/"),
            s3_dry_run=_bool_env(os.getenv("S3_DRY_RUN"), default=False),
            transcription_provider=os.getenv("TRANSCRIPTION_PROVIDER", "amazon-transcribe"),
            amazon_transcribe_language_code=os.getenv("AMAZON_TRANSCRIBE_LANGUAGE_CODE") or None,
            amazon_transcribe_identify_language=_bool_env(
                os.getenv("AMAZON_TRANSCRIBE_IDENTIFY_LANGUAGE"),
                default=os.getenv("AMAZON_TRANSCRIBE_LANGUAGE_CODE") in {None, ""},
            ),
            amazon_transcribe_input_prefix=os.getenv(
                "AMAZON_TRANSCRIBE_INPUT_PREFIX", "transcribe/input/"
            ),
            amazon_transcribe_output_prefix=os.getenv(
                "AMAZON_TRANSCRIBE_OUTPUT_PREFIX", "transcribe/output/"
            ),
            amazon_transcribe_poll_seconds=float(os.getenv("AMAZON_TRANSCRIBE_POLL_SECONDS", "5")),
            amazon_transcribe_timeout_seconds=int(
                os.getenv("AMAZON_TRANSCRIBE_TIMEOUT_SECONDS", "900")
            ),
            openai_audio_base_url=os.getenv("OPENAI_AUDIO_BASE_URL", "http://localhost:8000/v1"),
            openai_audio_api_key=os.getenv("OPENAI_AUDIO_API_KEY", "cant-be-empty"),
            whisper_model=os.getenv("WHISPER_MODEL", "Systran/faster-distil-whisper-small.en"),
            firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY") or None,
            lancedb_uri=os.getenv("LANCEDB_URI") or None,
            lancedb_table=os.getenv("LANCEDB_TABLE", "captures"),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "stub"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        )


def upload_original_to_s3(
    local_path: str,
    capture_id: str,
    asset_id: str,
    original_filename: str,
    settings: ToolSettings | None = None,
) -> dict[str, str]:
    settings = settings or ToolSettings.from_env()
    source = _resolve_path(local_path, settings)
    key = _join_s3_key(settings.s3_prefix, capture_id, asset_id, Path(original_filename).name)
    bucket = settings.s3_bucket or "local-dev"

    if settings.s3_dry_run or not settings.s3_bucket:
        target = settings.content_repo_path / ".content-archiver" / "blob-store" / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return {"original_uri": f"s3://{bucket}/{key}"}

    client = _boto3_client("s3", settings)
    client.upload_file(str(source), settings.s3_bucket, key)
    return {"original_uri": f"s3://{settings.s3_bucket}/{key}"}


def resize_image(
    input_path: str,
    output_path: str,
    max_width: int = 1280,
    settings: ToolSettings | None = None,
) -> dict[str, str]:
    settings = settings or ToolSettings.from_env()
    source = _resolve_path(input_path, settings)
    target = _target_path(output_path, settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
    except ImportError:
        shutil.copy2(source, target)
        return {"output_path": _rel(target, settings)}

    with Image.open(source) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            ratio = max_width / image.width
            image = image.resize((max_width, max(1, int(image.height * ratio))))
        image.save(target, format="JPEG", quality=82, optimize=True)
    return {"output_path": _rel(target, settings)}


def extract_video_frames(
    video_path: str,
    output_dir: str,
    count: int = 2,
    settings: ToolSettings | None = None,
) -> dict[str, list[str]]:
    settings = settings or ToolSettings.from_env()
    source = _resolve_path(video_path, settings)
    target_dir = _target_path(output_dir, settings)
    target_dir.mkdir(parents=True, exist_ok=True)
    pattern = target_dir / "frame-%03d.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vf",
            "select='not(mod(n,60))',scale=1280:-1",
            "-vsync",
            "vfr",
            "-frames:v",
            str(count),
            str(pattern),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return {"frame_paths": [_rel(path, settings) for path in sorted(target_dir.glob("frame-*.jpg"))[:count]]}


def extract_audio(
    video_path: str,
    output_path: str,
    settings: ToolSettings | None = None,
) -> dict[str, str]:
    settings = settings or ToolSettings.from_env()
    source = _resolve_path(video_path, settings)
    target = _target_path(output_path, settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return {"audio_path": _rel(target, settings)}


def transcribe_audio(audio_path: str, settings: ToolSettings | None = None) -> dict[str, str]:
    settings = settings or ToolSettings.from_env()
    provider = settings.transcription_provider.lower()
    path = _resolve_path(audio_path, settings)
    if provider in {"stub", "none", "disabled"}:
        return {"transcript": f"# Transcript\n\nTranscription disabled. Source: `{path.name}`."}
    if provider in {"amazon-transcribe", "aws-transcribe", "transcribe"}:
        return {"transcript": _transcribe_with_amazon(path, settings)}
    if provider in {"openai-compatible", "speaches", "lmstudio"}:
        return {"transcript": _transcribe_openai_compatible(path, settings)}
    raise ValueError(f"Unsupported transcription provider: {settings.transcription_provider}")


def pdf_to_markdown(
    pdf_path: str,
    output_path: str,
    settings: ToolSettings | None = None,
) -> dict[str, str]:
    settings = settings or ToolSettings.from_env()
    source = _resolve_path(pdf_path, settings)
    target = _target_path(output_path, settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        from markitdown import MarkItDown
    except ImportError:
        target.write_text(
            "# PDF extraction unavailable\n\n"
            "Install `markitdown` to extract this PDF.\n\n"
            f"Original file: `{source.name}`\n",
            encoding="utf-8",
        )
        return {"markdown_path": _rel(target, settings)}

    result = MarkItDown().convert(str(source))
    markdown = getattr(result, "text_content", None) or str(result)
    target.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    return {"markdown_path": _rel(target, settings)}


def crawl_url_to_markdown(
    url: str,
    output_path: str,
    settings: ToolSettings | None = None,
) -> dict[str, str]:
    settings = settings or ToolSettings.from_env()
    target = _target_path(output_path, settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    markdown = _crawl_with_firecrawl(url, settings.firecrawl_api_key) if settings.firecrawl_api_key else _crawl_stdlib(url)
    target.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    return {"markdown_path": _rel(target, settings)}


def index_lancedb(
    paths: list[str] | None = None,
    settings: ToolSettings | None = None,
) -> dict[str, Any]:
    settings = settings or ToolSettings.from_env()
    markdown_paths = _markdown_paths(paths, settings)
    previous = _load_index_manifest(settings)
    changed = [path for path in markdown_paths if _sha256(path) != previous.get(_rel(path, settings))]

    records: list[dict[str, Any]] = []
    for path in changed:
        records.extend(_records_for_markdown(path, settings))

    if records:
        _upsert_lancedb(records, settings)

    local_records = [
        record
        for path in markdown_paths
        for record in _records_for_markdown(path, settings, include_embedding=False)
    ]
    _write_jsonl_records(local_records, settings)

    now = _now()
    manifest = {
        "version": 1,
        "uri": settings.lancedb_uri or "",
        "table": settings.lancedb_table,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "last_indexed_at": now,
        "files": {_rel(path, settings): _sha256(path) for path in markdown_paths},
    }
    manifest_path = settings.content_repo_path / "index" / "lancedb-manifest.yml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    report_path = settings.content_repo_path / "index" / "index-report.json"
    report = {
        "indexed_at": now,
        "scanned_files": len(markdown_paths),
        "changed_files": len(changed),
        "chunks": len(records),
        "records": [
            {
                "id": record["id"],
                "capture_id": record["capture_id"],
                "path": record["path"],
                "chunk_index": record["chunk_index"],
            }
            for record in records
        ],
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "scanned_files": len(markdown_paths),
        "changed_files": len(changed),
        "chunks": len(records),
        "report_path": _rel(report_path, settings),
    }


def semantic_search(
    query: str,
    limit: int = 10,
    filters: dict[str, Any] | None = None,
    settings: ToolSettings | None = None,
) -> dict[str, Any]:
    settings = settings or ToolSettings.from_env()
    if settings.lancedb_uri and settings.embedding_provider.lower() not in {"stub", "none"}:
        try:
            return {"results": _semantic_search_lancedb(query, limit, filters or {}, settings)}
        except Exception:
            pass
    return {"results": _semantic_search_local(query, limit, filters or {}, settings)}


def _semantic_search_lancedb(
    query: str,
    limit: int,
    filters: dict[str, Any],
    settings: ToolSettings,
) -> list[dict[str, Any]]:
    import lancedb

    embedding = _embed_texts([query], settings)[0]
    db = lancedb.connect(settings.lancedb_uri)
    table = db.open_table(settings.lancedb_table)
    search = table.search(embedding).limit(limit)
    if filters.get("capture_id"):
        search = search.where(f"capture_id = '{filters['capture_id']}'")
    return search.to_list()


def _semantic_search_local(
    query: str,
    limit: int,
    filters: dict[str, Any],
    settings: ToolSettings,
) -> list[dict[str, Any]]:
    records = _load_local_records(settings)
    if not records:
        records = [
            record
            for path in _markdown_paths(None, settings)
            for record in _records_for_markdown(path, settings, include_embedding=False)
        ]
    query_tokens = set(_tokens(query))
    results = []
    for record in records:
        if filters.get("capture_id") and record.get("capture_id") != filters["capture_id"]:
            continue
        content_tokens = set(_tokens(str(record.get("content", ""))))
        score = len(query_tokens & content_tokens) / max(len(query_tokens), 1)
        if score <= 0:
            continue
        results.append(
            {
                "score": round(score, 4),
                "capture_id": record.get("capture_id"),
                "path": record.get("path"),
                "chunk_index": record.get("chunk_index"),
                "content": str(record.get("content", ""))[:800],
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def _records_for_markdown(
    path: Path,
    settings: ToolSettings,
    *,
    include_embedding: bool = True,
) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8")
    chunks = _chunk_text(content)
    embeddings = _embed_texts(chunks, settings) if include_embedding else [[] for _ in chunks]
    now = _now()
    records = []
    for index, chunk in enumerate(chunks):
        records.append(
            {
                "id": hashlib.sha256(f"{_rel(path, settings)}:{index}".encode()).hexdigest(),
                "capture_id": _capture_id(path, settings),
                "path": _rel(path, settings),
                "chunk_index": index,
                "content": chunk,
                "content_type": "markdown",
                "created_at": now,
                "updated_at": now,
                "source": "git",
                "s3_uri": None,
                "tags": [],
                "embedding": embeddings[index],
            }
        )
    return records


def _upsert_lancedb(records: list[dict[str, Any]], settings: ToolSettings) -> None:
    if not settings.lancedb_uri or settings.embedding_provider.lower() in {"stub", "none"}:
        return
    import lancedb

    db = lancedb.connect(settings.lancedb_uri)
    try:
        table = db.open_table(settings.lancedb_table)
    except Exception:
        db.create_table(settings.lancedb_table, data=records)
        return
    if hasattr(table, "merge_insert"):
        table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(records)
    else:
        table.add(records)


def _embed_texts(texts: list[str], settings: ToolSettings) -> list[list[float]]:
    provider = settings.embedding_provider.lower()
    if provider in {"openai-compatible", "openai"} and settings.openai_api_key:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        response = client.embeddings.create(model=settings.embedding_model, input=texts)
        return [list(item.embedding) for item in response.data]
    return [_hash_embedding(text) for text in texts]


def _write_jsonl_records(records: list[dict[str, Any]], settings: ToolSettings) -> None:
    target = settings.content_repo_path / "index" / "semantic-records.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _load_local_records(settings: ToolSettings) -> list[dict[str, Any]]:
    path = settings.content_repo_path / "index" / "semantic-records.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _markdown_paths(paths: list[str] | None, settings: ToolSettings) -> list[Path]:
    if paths:
        return [_resolve_path(path, settings) for path in paths]
    captures_dir = settings.content_repo_path / "captures"
    return sorted(captures_dir.glob("**/*.md")) if captures_dir.exists() else []


def _load_index_manifest(settings: ToolSettings) -> dict[str, str]:
    path = settings.content_repo_path / "index" / "lancedb-manifest.yml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    files = data.get("files") or {}
    return {str(key): str(value) for key, value in files.items()} if isinstance(files, dict) else {}


def _transcribe_with_amazon(path: Path, settings: ToolSettings) -> str:
    if not settings.s3_bucket:
        raise RuntimeError("S3_BUCKET is required for Amazon Transcribe.")
    s3 = _boto3_client("s3", settings)
    transcribe = _boto3_client("transcribe", settings)
    job_name = f"content-archive-{_safe_stem(path.stem)}-{uuid.uuid4().hex[:12]}"
    input_key = _join_s3_key(settings.amazon_transcribe_input_prefix, job_name, path.name)
    output_key = _join_s3_key(settings.amazon_transcribe_output_prefix, f"{job_name}.json")
    s3.upload_file(str(path), settings.s3_bucket, input_key)
    request = {
        "TranscriptionJobName": job_name,
        "Media": {"MediaFileUri": f"s3://{settings.s3_bucket}/{input_key}"},
        "OutputBucketName": settings.s3_bucket,
        "OutputKey": output_key,
    }
    media_format = _amazon_media_format(path)
    if media_format:
        request["MediaFormat"] = media_format
    if settings.amazon_transcribe_language_code:
        request["LanguageCode"] = settings.amazon_transcribe_language_code
    elif settings.amazon_transcribe_identify_language:
        request["IdentifyLanguage"] = True
    else:
        raise RuntimeError("Amazon Transcribe requires language code or language identification.")
    transcribe.start_transcription_job(**request)
    _wait_for_transcribe(transcribe, job_name, settings)
    output = s3.get_object(Bucket=settings.s3_bucket, Key=output_key)
    payload = json.loads(output["Body"].read().decode("utf-8"))
    transcripts = payload.get("results", {}).get("transcripts", [])
    return "\n\n".join(item.get("transcript", "").strip() for item in transcripts).strip()


def _transcribe_openai_compatible(path: Path, settings: ToolSettings) -> str:
    from openai import OpenAI

    client = OpenAI(base_url=settings.openai_audio_base_url, api_key=settings.openai_audio_api_key)
    with path.open("rb") as audio_file:
        result = client.audio.transcriptions.create(model=settings.whisper_model, file=audio_file)
    return str(getattr(result, "text", None) or (result.get("text") if isinstance(result, dict) else result))


def _wait_for_transcribe(client: Any, job_name: str, settings: ToolSettings) -> None:
    deadline = time.monotonic() + settings.amazon_transcribe_timeout_seconds
    while time.monotonic() < deadline:
        job = client.get_transcription_job(TranscriptionJobName=job_name)["TranscriptionJob"]
        status = job["TranscriptionJobStatus"]
        if status == "COMPLETED":
            return
        if status == "FAILED":
            raise RuntimeError(f"Amazon Transcribe failed: {job.get('FailureReason', 'unknown')}")
        time.sleep(settings.amazon_transcribe_poll_seconds)
    raise TimeoutError(f"Amazon Transcribe timed out: {job_name}")


def _crawl_with_firecrawl(url: str, api_key: str | None) -> str:
    import requests

    response = requests.post(
        "https://api.firecrawl.dev/v1/scrape",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"url": url, "formats": ["markdown"]},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or payload
    markdown = data.get("markdown")
    if not markdown:
        raise RuntimeError("Firecrawl did not return markdown.")
    return f"# Source\n\nURL: {url}\n\n{markdown}"


def _crawl_stdlib(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "content-archiver-mcp/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode(response.headers.get_content_charset() or "utf-8", "replace")
    title = _extract_title(raw) or url
    body = _html_to_text(raw)
    return f"# {title}\n\nURL: {url}\n\n{body}"


def _boto3_client(service_name: str, settings: ToolSettings) -> Any:
    import boto3

    kwargs = {}
    if settings.aws_profile:
        kwargs["profile_name"] = settings.aws_profile
    if settings.aws_region:
        kwargs["region_name"] = settings.aws_region
    return boto3.Session(**kwargs).client(service_name)


def _resolve_path(value: str, settings: ToolSettings) -> Path:
    path = Path(value)
    return path if path.is_absolute() else settings.content_repo_path / path


def _target_path(value: str, settings: ToolSettings) -> Path:
    return _resolve_path(value, settings)


def _rel(path: Path, settings: ToolSettings) -> str:
    try:
        return path.resolve().relative_to(settings.content_repo_path.resolve()).as_posix()
    except ValueError:
        return str(path)


def _join_s3_key(*parts: str) -> str:
    return "/".join(str(part).strip("/") for part in parts if str(part).strip("/"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def _hash_embedding(text: str, dimensions: int = 16) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [round((digest[index] / 255 * 2) - 1, 6) for index in range(dimensions)]


def _capture_id(path: Path, settings: ToolSettings) -> str:
    rel = path.resolve().relative_to(settings.content_repo_path.resolve())
    if len(rel.parts) >= 3 and rel.parts[0] == "captures" and rel.parts[1] == "_inbox":
        return rel.parts[2]
    if len(rel.parts) >= 2 and rel.parts[0] == "captures":
        return rel.parts[1]
    return "unknown"


def _tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_stem(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")[:48] or "audio"


def _amazon_media_format(path: Path) -> str | None:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"mp3", "mp4", "wav", "flac", "ogg", "amr", "webm", "m4a"}:
        return suffix
    if suffix in {"oga", "opus"}:
        return "ogg"
    return None


def _extract_title(raw_html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def _html_to_text(raw_html: str) -> str:
    raw_html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw_html)
    raw_html = re.sub(r"(?s)<br\s*/?>", "\n", raw_html)
    raw_html = re.sub(r"(?s)</p\s*>", "\n\n", raw_html)
    text = re.sub(r"(?s)<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _bool_env(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}
