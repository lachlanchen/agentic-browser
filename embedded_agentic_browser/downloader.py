"""Guarded public-domain downloader for the agentic browser."""

from __future__ import annotations

import mimetypes
import re
import time
import urllib.parse
import urllib.request
from email.message import Message
from pathlib import Path
from typing import BinaryIO

from embedded_agentic_browser.safety import classify_url


DEFAULT_MAX_BYTES = 250 * 1024 * 1024
CHUNK_SIZE = 1024 * 256
DOWNLOADABLE_CONTENT_TYPES = (
    "application/epub+zip",
    "application/pdf",
    "application/octet-stream",
    "application/x-mobipocket-ebook",
    "application/zip",
    "text/plain",
    "text/html",
)


class DownloadError(RuntimeError):
    pass


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^\w.\-+() \[\]\u4e00-\u9fff\u3040-\u30ff]+", "_", value, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._-")
    return cleaned[:180] or "download"


def filename_from_content_disposition(header: str) -> str:
    message = Message()
    message["Content-Disposition"] = header
    filename = message.get_filename() or ""
    return sanitize_filename(filename) if filename else ""


def filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = Path(urllib.parse.unquote(parsed.path)).name
    if not name or name in {"/", "."}:
        name = parsed.netloc
    return sanitize_filename(name)


def extension_for_content_type(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized == "application/epub+zip":
        return ".epub"
    return mimetypes.guess_extension(normalized) or ""


def choose_filename(url: str, headers: object, requested_filename: str = "") -> str:
    if requested_filename:
        base = sanitize_filename(requested_filename)
    else:
        getheader = getattr(headers, "get", None)
        disposition = str(getheader("Content-Disposition", "") if getheader else "")
        base = filename_from_content_disposition(disposition) or filename_from_url(url)
    suffix = Path(base).suffix
    getheader = getattr(headers, "get", None)
    content_type = str(getheader("Content-Type", "") if getheader else "")
    if not suffix and content_type:
        base += extension_for_content_type(content_type)
    return sanitize_filename(base)


def unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(2, 10000):
        next_candidate = directory / f"{stem}-{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
    raise DownloadError(f"Could not choose unique filename for {filename}")


def ensure_download_allowed(url: str) -> str:
    policy = classify_url(url)
    if not policy.allowed:
        raise DownloadError(policy.stop_reason)
    if not policy.is_public_domain:
        raise DownloadError("Downloads are only enabled for public-domain/open source hosts.")
    return policy.url


def validate_content_type(content_type: str) -> None:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if not normalized:
        return
    if normalized in DOWNLOADABLE_CONTENT_TYPES:
        return
    if normalized.startswith("text/"):
        return
    raise DownloadError(f"Unexpected download content type: {content_type}")


def copy_response(response: BinaryIO, destination: Path, max_bytes: int) -> int:
    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                handle.close()
                destination.unlink(missing_ok=True)
                raise DownloadError(f"Download exceeded limit of {max_bytes} bytes")
            handle.write(chunk)
    return total


def download_public_file(
    url: str,
    download_dir: Path,
    requested_filename: str = "",
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict:
    safe_url = ensure_download_allowed(url)
    request = urllib.request.Request(
        safe_url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AgenticBrowser/1.0",
        },
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=60) as response:
        headers = response.headers
        content_type = headers.get("Content-Type", "")
        validate_content_type(content_type)
        content_length = headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise DownloadError(f"Download size {content_length} exceeds limit of {max_bytes} bytes")
        filename = choose_filename(response.geturl(), headers, requested_filename)
        destination = unique_path(download_dir, filename)
        bytes_written = copy_response(response, destination, max_bytes)
    return {
        "ok": True,
        "url": safe_url,
        "final_url": response.geturl(),
        "path": str(destination),
        "filename": destination.name,
        "bytes": bytes_written,
        "content_type": content_type,
        "duration_seconds": round(time.time() - started, 2),
    }
