"""Navigation policy for the embedded agentic browser."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, asdict


PUBLIC_DOMAIN_HOST_PARTS = (
    "wikisource.org",
    "ctext.org",
    "dl.ndl.go.jp",
    "aozora.gr.jp",
    "gutenberg.org",
    "standardebooks.org",
    "archive.org",
)
SHADOW_LIBRARY_HOST_PARTS = (
    "libgen.",
    "library.lol",
    "z-lib.",
    "zlibrary",
    "annas-archive",
)
DESIGN_TOOL_HOST_PARTS = (
    "figma.com",
    "biorender.com",
)
DOWNLOAD_WORDS = (
    "download",
    "get",
    "mirror",
    "ipfs",
    "torrent",
    "下载",
    "下載",
)
BINARY_EXTENSIONS = (".pdf", ".epub", ".mobi", ".azw", ".azw3", ".zip", ".rar", ".djvu")


@dataclass(frozen=True)
class NavigationPolicy:
    url: str
    host: str
    allowed: bool
    mode: str
    is_public_domain: bool
    is_shadow_library: bool
    is_design_tool: bool
    looks_download: bool
    looks_binary: bool
    stop_reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def normalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        raise ValueError("URL is required")
    parsed = urllib.parse.urlparse(value)
    if not parsed.scheme:
        value = "https://" + value
        parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https", "file"}:
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    return value


def classify_url(url: str) -> NavigationPolicy:
    normalized = normalize_url(url)
    parsed = urllib.parse.urlparse(normalized)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    is_public = any(part in host for part in PUBLIC_DOMAIN_HOST_PARTS)
    is_shadow = any(part in host for part in SHADOW_LIBRARY_HOST_PARTS)
    is_design = any(part in host for part in DESIGN_TOOL_HOST_PARTS)
    looks_binary = path.endswith(BINARY_EXTENSIONS)
    looks_download = looks_binary or any(word in path for word in DOWNLOAD_WORDS)

    allowed = True
    mode = "regular"
    stop_reason = ""

    if is_public:
        mode = "public-domain"
    elif is_design:
        mode = "design-tool"
    elif is_shadow:
        mode = "shadow-library-inspection"

    if is_shadow and looks_download:
        allowed = False
        stop_reason = "Blocked shadow-library download/mirror/direct-file URL."
    elif is_shadow and path in {"", "/"} and parsed.query:
        allowed = False
        stop_reason = "Blocked shadow-library resolver/mirror URL."
    elif is_shadow and not (path.startswith("/search") or path.startswith("/book") or path.startswith("/links") or path in {"", "/"}):
        allowed = False
        stop_reason = "Blocked shadow-library navigation beyond search/detail inspection pages."
    elif looks_binary and not is_public:
        allowed = False
        stop_reason = "Blocked direct binary URL unless the host is a public-domain/open source."

    return NavigationPolicy(
        url=normalized,
        host=host,
        allowed=allowed,
        mode=mode,
        is_public_domain=is_public,
        is_shadow_library=is_shadow,
        is_design_tool=is_design,
        looks_download=looks_download,
        looks_binary=looks_binary,
        stop_reason=stop_reason,
    )
