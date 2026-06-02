#!/usr/bin/env python3
"""Chrome/CDP helper for collecting public-domain PDFs into library/.

The LibGen mode opens matching record pages and writes a manifest. Import and
direct-download modes handle local files or direct public-domain URLs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websocket


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = int(os.environ.get("BOOKS_CHROME_PORT", "9222"))
DEFAULT_PROFILE_DIR = Path.home() / ".cache" / "books-libgen-chrome"
DEFAULT_LIBRARY_DIR = REPO_ROOT / "library"
DEFAULT_DOWNLOAD_DIR = DEFAULT_LIBRARY_DIR / "_incoming"
DEFAULT_AKUTAGAWA_SEARCH_URL = (
    "https://libgen.pw/search?query=%E8%8A%A5%E5%B7%9D%E9%BE%99%E4%B9%8B%E4%BB%8B"
    "&collection=libgen"
)
AKUTAGAWA_TITLES = [
    "芥川龙之介全集 1",
    "芥川龙之介全集 2",
    "芥川龙之介全集 3",
    "芥川龙之介全集 4",
    "芥川龙之介全集 5",
]
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
BLOCKED_DIRECT_DOWNLOAD_HOSTS = {
    "libgen.pw",
    "www.libgen.pw",
    "libgen.is",
    "www.libgen.is",
    "libgen.rs",
    "www.libgen.rs",
    "library.lol",
}
BLOCKED_DIRECT_DOWNLOAD_HOST_PARTS = (
    "libgen.",
    "library.lol",
)


class ToolError(RuntimeError):
    pass


@dataclass
class BookRecord:
    id: str
    title: str
    author: list[str]
    language: str
    extension: str
    file_size: int
    links_url: str

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "BookRecord":
        book_id = str(payload.get("id") or "").strip()
        if not book_id:
            raise ToolError(f"Search result is missing id: {payload}")
        return cls(
            id=book_id,
            title=str(payload.get("title") or "").strip(),
            author=[str(author).strip() for author in payload.get("author") or [] if str(author).strip()],
            language=str(payload.get("language") or "").strip(),
            extension=str(payload.get("fileExtension") or "").strip().lower(),
            file_size=int(payload.get("fileSize") or 0),
            links_url=f"https://libgen.pw/links/{book_id}",
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "language": self.language,
            "extension": self.extension,
            "file_size": self.file_size,
            "links_url": self.links_url,
            "suggested_filename": suggested_filename(self),
        }


class CDPPage:
    def __init__(self, websocket_url: str, origin: str) -> None:
        self.ws = websocket.create_connection(websocket_url, timeout=20, origin=origin)
        self._id = 0
        self.call("Runtime.enable")
        self.call("Page.enable")

    def close(self) -> None:
        self.ws.close()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self._id:
                return message

    def evaluate(self, expression: str) -> Any:
        response = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        )
        result = response.get("result", {})
        if "exceptionDetails" in result:
            raise ToolError(json.dumps(result["exceptionDetails"], ensure_ascii=False, indent=2))
        return result.get("result", {}).get("value")

    def bring_to_front(self) -> None:
        self.call("Page.bringToFront")

    def set_download_dir(self, download_dir: Path) -> None:
        download_dir.mkdir(parents=True, exist_ok=True)
        for method in ("Browser.setDownloadBehavior", "Page.setDownloadBehavior"):
            response = self.call(
                method,
                {"behavior": "allow", "downloadPath": str(download_dir.resolve())},
            )
            if "error" not in response:
                return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    libgen = subparsers.add_parser("libgen-open", help="Open matching LibGen records in Chrome tabs.")
    add_chrome_args(libgen)
    add_libgen_args(libgen)

    akutagawa = subparsers.add_parser(
        "akutagawa-open",
        help="Shortcut for the five 芥川龙之介全集 PDF records from the current search.",
    )
    add_chrome_args(akutagawa)
    akutagawa.add_argument("--manifest", type=Path, default=DEFAULT_LIBRARY_DIR / "akutagawa-libgen-manifest.json")
    akutagawa.add_argument("--dry-run", action="store_true")

    importer = subparsers.add_parser("import-downloads", help="Copy or move downloaded PDFs into library/.")
    importer.add_argument("--source-dir", type=Path, default=Path.home() / "Downloads")
    importer.add_argument("--library-dir", type=Path, default=DEFAULT_LIBRARY_DIR)
    importer.add_argument("--manifest", type=Path, default=None)
    importer.add_argument("--collection", default="public-domain")
    importer.add_argument("--move", action="store_true", help="Move files instead of copying.")
    importer.add_argument("--extension", default="pdf")
    importer.add_argument("--dry-run", action="store_true")

    direct = subparsers.add_parser("download-direct", help="Download direct public-domain PDF URLs.")
    direct.add_argument("--manifest", type=Path, required=True)
    direct.add_argument("--library-dir", type=Path, default=DEFAULT_LIBRARY_DIR)
    direct.add_argument(
        "--public-domain-confirmed",
        action="store_true",
        help="Required confirmation that every direct URL is lawful/public-domain.",
    )
    direct.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def add_chrome_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--download-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR)
    parser.add_argument("--no-launch", action="store_true", help="Fail if Chrome is not already on the CDP port.")


def add_libgen_args(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--search-url", default="")
    source.add_argument("--query", default="")
    parser.add_argument("--collection", default="libgen")
    parser.add_argument("--title", action="append", default=[])
    parser.add_argument("--titles-file", type=Path)
    parser.add_argument("--extension", default="pdf")
    parser.add_argument("--language", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_LIBRARY_DIR / "libgen-open-manifest.json")
    parser.add_argument("--dry-run", action="store_true")


def debug_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def request_json(url: str, path: str, method: str = "GET") -> Any:
    request = urllib.request.Request(url + path, method=method, headers=HTTP_HEADERS)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def urlopen_json(url: str, timeout: int = 30) -> Any:
    request = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def debug_port_alive(port: int) -> bool:
    try:
        request_json(debug_url(port), "/json/version")
        return True
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
        return False


def remove_stale_singletons(profile_dir: Path) -> None:
    active = subprocess.run(
        ["pgrep", "-af", str(profile_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    if active.stdout.strip():
        return
    for name in ("SingletonCookie", "SingletonLock", "SingletonSocket"):
        path = profile_dir / name
        if path.exists() or path.is_symlink():
            path.unlink()


def launch_chrome(port: int, profile_dir: Path) -> None:
    profile_dir = profile_dir.expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)
    remove_stale_singletons(profile_dir)
    chrome_bin = os.environ.get("CHROME_BIN", "google-chrome")
    command = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-allow-origins={debug_url(port)}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "about:blank",
    ]
    log_path = Path("/tmp/books_libgen_chrome.log")
    handle = log_path.open("ab")
    subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)


def ensure_chrome(port: int, profile_dir: Path, no_launch: bool) -> None:
    if debug_port_alive(port):
        return
    if no_launch:
        raise ToolError(f"Chrome DevTools is not available at {debug_url(port)}")
    launch_chrome(port, profile_dir)
    deadline = time.time() + 30
    while time.time() < deadline:
        if debug_port_alive(port):
            return
        time.sleep(0.5)
    raise ToolError(f"Chrome DevTools did not become available at {debug_url(port)}")


def new_tab(port: int, url: str) -> CDPPage:
    encoded = urllib.parse.quote(url, safe="")
    base = debug_url(port)
    try:
        target = request_json(base, f"/json/new?{encoded}", method="PUT")
    except urllib.error.HTTPError:
        target = request_json(base, f"/json/new?{encoded}", method="GET")
    return CDPPage(target["webSocketDebuggerUrl"], origin=base)


def search_url_from_args(args: argparse.Namespace) -> str:
    if getattr(args, "search_url", ""):
        return args.search_url
    query = urllib.parse.quote(args.query)
    collection = urllib.parse.quote(args.collection)
    return f"https://libgen.pw/search?query={query}&collection={collection}"


def api_url_from_search(search_url: str, limit_from: int = 0) -> str:
    parsed = urllib.parse.urlparse(search_url)
    params = urllib.parse.parse_qs(parsed.query)
    query = params.get("query", [""])[0]
    collection = params.get("collection", ["libgen"])[0]
    encoded = urllib.parse.urlencode({"query": query, "collection": collection, "from": str(limit_from)})
    return f"https://libgen.pw/api/search/by-params?{encoded}"


def fetch_libgen_records(search_url: str) -> list[BookRecord]:
    payload = urlopen_json(api_url_from_search(search_url), timeout=30)
    books = payload.get("result", {}).get("books") or []
    return [BookRecord.from_api(book) for book in books]


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def load_titles(args: argparse.Namespace) -> list[str]:
    titles = list(getattr(args, "title", []) or [])
    if getattr(args, "titles_file", None):
        titles.extend(
            line.strip()
            for line in args.titles_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return titles


def match_records(
    records: list[BookRecord],
    titles: list[str],
    extension: str,
    language: str,
    limit: int,
) -> list[BookRecord]:
    extension = extension.strip().lower()
    language = language.strip().lower()
    filtered = [
        record
        for record in records
        if (not extension or record.extension == extension)
        and (not language or record.language.lower() == language)
    ]
    if not titles:
        return filtered[:limit]

    matches: list[BookRecord] = []
    used_ids: set[str] = set()
    for title in titles:
        wanted = normalize_text(title)
        exact = [record for record in filtered if normalize_text(record.title) == wanted]
        partial = [record for record in filtered if wanted in normalize_text(record.title)]
        candidates = exact or partial
        if not candidates:
            print(f"not found: {title}", file=sys.stderr)
            continue
        record = candidates[0]
        if record.id not in used_ids:
            matches.append(record)
            used_ids.add(record.id)
    return matches[:limit]


def sanitize_filename(value: str, fallback: str = "book") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:180].rstrip(" .") or fallback


def primary_author(record: BookRecord) -> str:
    if not record.author:
        return ""
    author = re.sub(r"\s+", " ", record.author[0]).strip()
    return author


def suggested_filename(record: BookRecord) -> str:
    author = primary_author(record)
    stem = f"{record.title} - {author}" if author else record.title
    return f"{sanitize_filename(stem, record.id)}.{record.extension or 'pdf'}"


def write_manifest(path: Path, records: list[BookRecord], search_url: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "search_url": search_url,
        "records": [record.as_dict() for record in records],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def command_libgen_open(args: argparse.Namespace, titles: list[str] | None = None, search_url: str | None = None) -> int:
    ensure_chrome(args.port, args.profile_dir, args.no_launch)
    search_url = search_url or search_url_from_args(args)
    records = fetch_libgen_records(search_url)
    matches = match_records(
        records,
        titles if titles is not None else load_titles(args),
        getattr(args, "extension", "pdf"),
        getattr(args, "language", ""),
        getattr(args, "limit", 100),
    )
    write_manifest(args.manifest, matches, search_url=search_url)

    print(f"matched records: {len(matches)}")
    print(f"manifest: {args.manifest}")
    for record in matches:
        print(f"- {record.title} [{record.extension}, {record.file_size} bytes] -> {record.links_url}")

    if args.dry_run:
        return 0

    search_page = new_tab(args.port, search_url)
    try:
        search_page.set_download_dir(args.download_dir)
        search_page.bring_to_front()
    finally:
        search_page.close()

    for record in matches:
        page = new_tab(args.port, record.links_url)
        try:
            page.set_download_dir(args.download_dir)
        finally:
            page.close()
        time.sleep(0.25)
    return 0


def command_akutagawa_open(args: argparse.Namespace) -> int:
    args.extension = "pdf"
    args.language = "zho"
    args.limit = 10
    return command_libgen_open(args, titles=AKUTAGAWA_TITLES, search_url=DEFAULT_AKUTAGAWA_SEARCH_URL)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return list(payload.get("records") or [])


def output_path(library_dir: Path, collection: str, filename: str) -> Path:
    directory = library_dir / sanitize_filename(collection, "collection")
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / sanitize_filename(filename)
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 2
    while True:
        numbered = candidate.with_name(f"{stem} ({index}){suffix}")
        if not numbered.exists():
            return numbered
        index += 1


def candidate_sources(source_dir: Path, extension: str) -> list[Path]:
    extension = extension.lower().lstrip(".")
    return sorted(path for path in source_dir.expanduser().glob(f"*.{extension}") if path.is_file())


def best_source_for_record(record: dict[str, Any], sources: list[Path]) -> Path | None:
    expected_size = int(record.get("file_size") or record.get("fileSize") or 0)
    title = normalize_text(str(record.get("title") or ""))
    suggested = normalize_text(Path(str(record.get("suggested_filename") or "")).stem)

    scored: list[tuple[int, Path]] = []
    for source in sources:
        source_norm = normalize_text(source.stem)
        score = 0
        if expected_size:
            delta = abs(source.stat().st_size - expected_size)
            if delta == 0:
                score += 100
            elif delta / max(expected_size, 1) < 0.03:
                score += 40
        if title and title in source_norm:
            score += 30
        if suggested and suggested in source_norm:
            score += 30
        if score:
            scored.append((score, source))
    if not scored:
        return None
    return sorted(scored, key=lambda item: (-item[0], item[1].name))[0][1]


def command_import_downloads(args: argparse.Namespace) -> int:
    source_dir = args.source_dir.expanduser()
    library_dir = args.library_dir.expanduser()
    if not source_dir.exists():
        raise ToolError(f"Source directory does not exist: {source_dir}")

    sources = candidate_sources(source_dir, args.extension)
    imported = 0

    if args.manifest:
        records = load_manifest(args.manifest)
        used: set[Path] = set()
        for record in records:
            source = best_source_for_record(record, [path for path in sources if path not in used])
            if source is None:
                print(f"missing local file for: {record.get('title')}", file=sys.stderr)
                continue
            used.add(source)
            filename = str(record.get("suggested_filename") or source.name)
            target = output_path(library_dir, args.collection, filename)
            print(f"{'move' if args.move else 'copy'}: {source} -> {target}")
            if not args.dry_run:
                if args.move:
                    shutil.move(str(source), target)
                else:
                    shutil.copy2(source, target)
            imported += 1
    else:
        for source in sources:
            target = output_path(library_dir, args.collection, source.name)
            print(f"{'move' if args.move else 'copy'}: {source} -> {target}")
            if not args.dry_run:
                if args.move:
                    shutil.move(str(source), target)
                else:
                    shutil.copy2(source, target)
            imported += 1

    print(f"imported: {imported}")
    return 0


def command_download_direct(args: argparse.Namespace) -> int:
    if not args.public_domain_confirmed:
        raise ToolError("--public-domain-confirmed is required for direct downloads")
    records = load_manifest(args.manifest)
    downloaded = 0
    for record in records:
        url = str(record.get("url") or "").strip()
        if not url:
            print(f"skip record without url: {record}", file=sys.stderr)
            continue
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()
        if host in BLOCKED_DIRECT_DOWNLOAD_HOSTS or any(part in host for part in BLOCKED_DIRECT_DOWNLOAD_HOST_PARTS):
            raise ToolError(f"Direct download mode does not fetch from shadow-library host: {host}")
        extension = Path(parsed.path).suffix.lstrip(".") or str(record.get("extension") or "pdf")
        title = str(record.get("title") or Path(parsed.path).stem or "book")
        raw_author = record.get("author") or ""
        if isinstance(raw_author, list):
            raw_author = raw_author[0] if raw_author else ""
        author = str(raw_author).strip()
        stem = f"{title} - {author}" if author else title
        filename = f"{sanitize_filename(stem)}.{extension}"
        target = output_path(args.library_dir.expanduser(), str(record.get("collection") or "public-domain"), filename)
        print(f"download: {url} -> {target}")
        if not args.dry_run:
            request = urllib.request.Request(url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        downloaded += 1
    print(f"downloaded: {downloaded}")
    return 0


def main() -> int:
    args = parse_args()
    try:
        if args.command == "libgen-open":
            return command_libgen_open(args)
        if args.command == "akutagawa-open":
            return command_akutagawa_open(args)
        if args.command == "import-downloads":
            return command_import_downloads(args)
        if args.command == "download-direct":
            return command_download_direct(args)
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    raise ToolError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
