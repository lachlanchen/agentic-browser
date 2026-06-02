#!/usr/bin/env python3
"""Local agentic browser controller for book-search workflows.

The app serves a small GUI and drives a real Chrome instance through the Chrome
DevTools Protocol. It is designed for step-by-step decisions: open pages,
inspect cards/links, ask Codex for a recommendation, then explicitly choose the
next action.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import time
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from public_domain_pdf_tool import (
    CDPPage,
    ToolError,
    debug_url,
    ensure_chrome,
    new_tab,
    request_json,
)


REPO_ROOT = Path(__file__).resolve().parent
SITE_ROOT = REPO_ROOT / "agentic_browser_site"
DEFAULT_BROWSER_PORT = 9223
DEFAULT_SERVER_PORT = 8789
DEFAULT_PROFILE_DIR = Path.home() / ".cache" / "books-agentic-browser-chrome"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_REASONING_EFFORT = "low"
LOG_DIR = REPO_ROOT / "library" / "agentic-browser"
ACTION_LOG = LOG_DIR / "actions.jsonl"
MAX_AUTOPILOT_STEPS = 8

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
DOWNLOAD_WORDS = (
    "download",
    "get",
    "mirror",
    "cloudflare",
    "ipfs",
    "torrent",
    "下载",
    "下載",
)
BINARY_EXTENSIONS = (".pdf", ".epub", ".mobi", ".azw", ".azw3", ".zip", ".rar", ".djvu")


class AgenticBrowserError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT)
    parser.add_argument("--browser-port", type=int, default=DEFAULT_BROWSER_PORT)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    return parser.parse_args()


def append_action(event: str, payload: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": event,
        **payload,
    }
    with ACTION_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def normalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        raise AgenticBrowserError("URL is required")
    parsed = urllib.parse.urlparse(value)
    if not parsed.scheme:
        value = "https://" + value
        parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https", "file"}:
        raise AgenticBrowserError(f"Unsupported URL scheme: {parsed.scheme}")
    return value


def host_policy(url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    is_shadow = any(part in host for part in SHADOW_LIBRARY_HOST_PARTS)
    is_public_domain = any(part in host for part in PUBLIC_DOMAIN_HOST_PARTS)
    looks_binary = path.endswith(BINARY_EXTENSIONS)
    looks_download = looks_binary or any(word in path for word in DOWNLOAD_WORDS)

    allowed = True
    stop_reason = ""
    if is_shadow and looks_download:
        allowed = False
        stop_reason = "Blocked shadow-library download/mirror URL. Open search/detail pages only."
    elif is_shadow and not (path.startswith("/search") or path.startswith("/links") or path in {"", "/"}):
        allowed = False
        stop_reason = "Blocked shadow-library navigation beyond search/detail pages."
    elif looks_binary and not is_public_domain:
        allowed = False
        stop_reason = "Blocked direct binary URL unless the host is a known public-domain source."

    return {
        "host": host,
        "is_shadow_library": is_shadow,
        "is_public_domain": is_public_domain,
        "looks_binary": looks_binary,
        "looks_download": looks_download,
        "allowed": allowed,
        "stop_reason": stop_reason,
    }


def browser_targets(browser_port: int) -> list[dict[str, Any]]:
    ensure_browser(browser_port)
    return [
        target
        for target in request_json(debug_url(browser_port), "/json/list")
        if target.get("type") == "page"
    ]


def ensure_browser(browser_port: int) -> None:
    ensure_chrome(browser_port, DEFAULT_PROFILE_DIR, no_launch=False)


def attach_page(browser_port: int, target_id: str) -> CDPPage:
    for target in browser_targets(browser_port):
        if target.get("id") == target_id:
            return CDPPage(target["webSocketDebuggerUrl"], origin=debug_url(browser_port))
    raise AgenticBrowserError(f"Target not found: {target_id}")


def active_or_first_target(browser_port: int, target_id: str | None) -> str:
    if target_id:
        return target_id
    targets = browser_targets(browser_port)
    if not targets:
        raise AgenticBrowserError("No browser tabs are available")
    return str(targets[0]["id"])


def page_snapshot(browser_port: int, target_id: str | None) -> dict[str, Any]:
    target = active_or_first_target(browser_port, target_id)
    page = attach_page(browser_port, target)
    try:
        snapshot = page.evaluate(
            r"""
(() => {
  const text = document.body ? document.body.innerText : "";
  const lines = text.split("\n").map(x => x.trim()).filter(Boolean);
  const pick = (root, sel) => (root.querySelector(sel)?.innerText || "").trim();
  const cards = [...document.querySelectorAll(".v-book-card")].map((card, index) => ({
    index,
    title: pick(card, ".v-book-card__title"),
    authors: [...card.querySelectorAll(".v-book-card__author")].map(x => x.innerText.trim()).filter(Boolean),
    year: pick(card, ".v-book-card__year"),
    lang: pick(card, ".v-book-card__lang"),
    file: pick(card, ".v-book-card__link"),
    text: card.innerText.trim().slice(0, 800)
  })).slice(0, 80);
  const links = [...document.querySelectorAll("a[href]")].map((a, index) => ({
    index,
    text: (a.innerText || a.textContent || a.getAttribute("title") || "").trim().slice(0, 220),
    href: a.href
  })).filter(x => x.href).slice(0, 220);
  const downloadish = links.filter(x => /download|pdf|epub|mobi|azw|djvu|下載|下载/i.test(`${x.text} ${x.href}`)).slice(0, 80);
  return {
    title: document.title,
    url: location.href,
    noResults: /no results found/i.test(text),
    textSample: lines.slice(0, 90),
    cards,
    links,
    downloadish,
    scroll: {x: window.scrollX, y: window.scrollY, height: document.body ? document.body.scrollHeight : 0}
  };
})()
"""
        )
    finally:
        page.close()
    snapshot["target_id"] = target
    snapshot["policy"] = host_policy(str(snapshot.get("url") or ""))
    return snapshot


def viewport_capture(browser_port: int, target_id: str | None, quality: int = 70) -> dict[str, Any]:
    target = active_or_first_target(browser_port, target_id)
    page = attach_page(browser_port, target)
    try:
        page.bring_to_front()
        metrics = page.evaluate(
            """
(() => ({
  title: document.title,
  url: location.href,
  viewport: {width: window.innerWidth, height: window.innerHeight, devicePixelRatio: window.devicePixelRatio},
  scroll: {x: window.scrollX, y: window.scrollY, height: document.body ? document.body.scrollHeight : 0}
}))()
"""
        )
        response = page.call(
            "Page.captureScreenshot",
            {
                "format": "jpeg",
                "quality": max(20, min(95, int(quality))),
                "fromSurface": True,
                "captureBeyondViewport": False,
            },
        )
        if "error" in response:
            raise AgenticBrowserError(str(response["error"]))
        screenshot = response.get("result", {}).get("data", "")
    finally:
        page.close()
    return {
        "target_id": target,
        "screenshot": f"data:image/jpeg;base64,{screenshot}",
        "metrics": metrics,
        "policy": host_policy(str(metrics.get("url") or "")),
    }


def browser_action(browser_port: int, target_id: str | None, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    target = active_or_first_target(browser_port, target_id)
    page = attach_page(browser_port, target)
    try:
        page.bring_to_front()
        if action == "click":
            x = float(payload.get("x") or 0)
            y = float(payload.get("y") or 0)
            for event_type in ("mousePressed", "mouseReleased"):
                page.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": event_type,
                        "x": x,
                        "y": y,
                        "button": "left",
                        "clickCount": 1,
                    },
                )
            result = {"clicked": {"x": x, "y": y}}
        elif action == "scroll":
            delta_y = int(payload.get("delta_y") or 700)
            page.evaluate(f"window.scrollBy(0, {delta_y}); ({'{'}x: window.scrollX, y: window.scrollY{'}'});")
            result = {"scrolled": delta_y}
        elif action == "type":
            text = str(payload.get("text") or "")
            page.call("Input.insertText", {"text": text})
            result = {"typed_length": len(text)}
        elif action == "key":
            key = str(payload.get("key") or "Enter")
            page.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": key})
            page.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": key})
            result = {"key": key}
        elif action == "reload":
            page.call("Page.reload", {"ignoreCache": bool(payload.get("ignore_cache", False))})
            result = {"reloaded": True}
        elif action == "back":
            page.evaluate("history.back(); true;")
            result = {"history": "back"}
        elif action == "forward":
            page.evaluate("history.forward(); true;")
            result = {"history": "forward"}
        elif action == "navigate":
            url = normalize_url(str(payload.get("url") or ""))
            policy = host_policy(url)
            if not policy["allowed"]:
                raise AgenticBrowserError(policy["stop_reason"])
            page.call("Page.navigate", {"url": url})
            result = {"navigated": url, "policy": policy}
        elif action == "wait":
            seconds = max(0.1, min(10.0, float(payload.get("seconds") or 1.0)))
            time.sleep(seconds)
            result = {"waited": seconds}
        else:
            raise AgenticBrowserError(f"Unsupported browser action: {action}")
    finally:
        page.close()
    append_action("browser_action", {"target_id": target, "action": action, "payload": payload, "result": result})
    return {"ok": True, "target_id": target, "action": action, "result": result}


def codex_decision_prompt(goal: str, snapshot: dict[str, Any]) -> str:
    compact = {
        "page": {
            "title": snapshot.get("title"),
            "url": snapshot.get("url"),
            "policy": snapshot.get("policy"),
            "noResults": snapshot.get("noResults"),
        },
        "cards": (snapshot.get("cards") or [])[:30],
        "downloadish": (snapshot.get("downloadish") or [])[:30],
        "textSample": (snapshot.get("textSample") or [])[:40],
    }
    return f"""
You are selecting the next safe browser action for a book-search workflow.

Goal:
{goal.strip() or "Inspect the page and choose the best candidate or next safe page."}

Rules:
- Prefer exact title, exact author, correct language, and complete multi-volume sets.
- Search pages are evidence; output a decision, not just a list of results.
- For public-domain hosts, you may recommend opening a source/detail/final pre-download page.
- For LibGen or other shadow-library hosts, do not recommend mirror/download/direct file pages.
- If the visible evidence is insufficient, set action to "hold" and explain what to search next.

Current page snapshot:
{json.dumps(compact, ensure_ascii=False, indent=2)}

Return JSON only.
""".strip()


def codex_autopilot_prompt(goal: str, snapshot: dict[str, Any], step_index: int) -> str:
    compact = {
        "step_index": step_index,
        "page": {
            "title": snapshot.get("title"),
            "url": snapshot.get("url"),
            "policy": snapshot.get("policy"),
            "noResults": snapshot.get("noResults"),
            "scroll": snapshot.get("scroll"),
        },
        "cards": (snapshot.get("cards") or [])[:30],
        "links": (snapshot.get("links") or [])[:80],
        "downloadish": (snapshot.get("downloadish") or [])[:40],
        "textSample": (snapshot.get("textSample") or [])[:50],
    }
    return f"""
You are the steering model for a monitored browser automation loop.

Goal:
{goal.strip() or "Search for a book, choose the best candidate, and stop with a clear decision."}

Allowed actions:
- select: final candidate found; stop.
- open_url: open a safe source/search/detail URL.
- scroll: scroll down/up to inspect more visible results.
- wait: wait for a dynamic page to render.
- hold: stop because the next step needs human review or the evidence is insufficient.
- stop: stop because the task is complete or unsafe.

Rules:
- Be conservative. One precise step is better than a risky chain.
- For LibGen or shadow-library hosts, use search/candidate/detail inspection only; never open mirror/download/direct-file pages.
- For public-domain hosts, you may open source/detail/final pre-download pages if policy permits.
- Prefer exact title, exact author, correct language, and complete sets.
- If a page has usable structured cards, choose from them instead of scrolling blindly.
- If all visible candidates are noisy or incomplete, use hold and explain the better query.

Snapshot:
{json.dumps(compact, ensure_ascii=False, indent=2)}

Return JSON only.
""".strip()


def run_codex_decision(goal: str, snapshot: dict[str, Any], model: str, reasoning_effort: str) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["select", "open_next", "hold", "stop"]},
            "selected_index": {"type": ["integer", "null"]},
            "selected_title": {"type": "string"},
            "selected_author": {"type": "string"},
            "selected_language": {"type": "string"},
            "next_url": {"type": "string"},
            "safety_stop": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": [
            "action",
            "selected_index",
            "selected_title",
            "selected_author",
            "selected_language",
            "next_url",
            "safety_stop",
            "reason",
        ],
        "additionalProperties": False,
    }
    prompt = codex_decision_prompt(goal, snapshot)
    with tempfile.TemporaryDirectory(prefix="agentic-browser-codex-") as temp_dir:
        schema_path = Path(temp_dir) / "schema.json"
        output_path = Path(temp_dir) / "result.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        cmd = [
            "codex",
            "exec",
            "--ephemeral",
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
            "-s",
            "read-only",
            "-C",
            str(REPO_ROOT),
            "--skip-git-repo-check",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            "-",
        ]
        result = subprocess.run(cmd, input=prompt, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-1600:]
            raise AgenticBrowserError(f"codex exec failed ({result.returncode}): {detail}")
        return json.loads(output_path.read_text(encoding="utf-8"))


def run_codex_autopilot_step(
    goal: str,
    snapshot: dict[str, Any],
    step_index: int,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["select", "open_url", "scroll", "wait", "hold", "stop"]},
            "selected_index": {"type": ["integer", "null"]},
            "selected_title": {"type": "string"},
            "selected_author": {"type": "string"},
            "selected_language": {"type": "string"},
            "next_url": {"type": "string"},
            "scroll_delta_y": {"type": "integer"},
            "wait_seconds": {"type": "number"},
            "safety_stop": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": [
            "action",
            "selected_index",
            "selected_title",
            "selected_author",
            "selected_language",
            "next_url",
            "scroll_delta_y",
            "wait_seconds",
            "safety_stop",
            "reason",
        ],
        "additionalProperties": False,
    }
    prompt = codex_autopilot_prompt(goal, snapshot, step_index)
    with tempfile.TemporaryDirectory(prefix="agentic-browser-autopilot-") as temp_dir:
        schema_path = Path(temp_dir) / "schema.json"
        output_path = Path(temp_dir) / "result.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        cmd = [
            "codex",
            "exec",
            "--ephemeral",
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
            "-s",
            "read-only",
            "-C",
            str(REPO_ROOT),
            "--skip-git-repo-check",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            "-",
        ]
        result = subprocess.run(cmd, input=prompt, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-1600:]
            raise AgenticBrowserError(f"codex exec failed ({result.returncode}): {detail}")
        return json.loads(output_path.read_text(encoding="utf-8"))


def run_autopilot(
    browser_port: int,
    target_id: str | None,
    goal: str,
    max_steps: int,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    target = active_or_first_target(browser_port, target_id)
    for step_index in range(1, min(max_steps, MAX_AUTOPILOT_STEPS) + 1):
        snapshot = page_snapshot(browser_port, target)
        decision = run_codex_autopilot_step(goal, snapshot, step_index, model, reasoning_effort)
        next_url = str(decision.get("next_url") or "").strip()
        if next_url:
            decision["next_url_policy"] = host_policy(next_url)
        step_record = {
            "step": step_index,
            "page_url": snapshot.get("url"),
            "page_title": snapshot.get("title"),
            "decision": decision,
        }
        steps.append(step_record)
        append_action("autopilot_decision", {"goal": goal, **step_record})

        action = decision.get("action")
        if action in {"select", "hold", "stop"} or decision.get("safety_stop"):
            return {"ok": True, "status": action, "target_id": target, "steps": steps}
        if action == "open_url":
            if not next_url:
                step_record["error"] = "open_url action had empty next_url"
                return {"ok": False, "status": "error", "target_id": target, "steps": steps}
            policy = host_policy(next_url)
            if not policy["allowed"]:
                step_record["blocked"] = policy
                append_action("autopilot_blocked", {"url": next_url, "policy": policy})
                return {"ok": False, "status": "blocked", "target_id": target, "steps": steps}
            browser_action(browser_port, target, "navigate", {"url": next_url})
            time.sleep(2.0)
        elif action == "scroll":
            delta = int(decision.get("scroll_delta_y") or 700)
            browser_action(browser_port, target, "scroll", {"delta_y": delta})
            time.sleep(0.8)
        elif action == "wait":
            seconds = max(0.1, min(10.0, float(decision.get("wait_seconds") or 1.0)))
            browser_action(browser_port, target, "wait", {"seconds": seconds})
        else:
            step_record["error"] = f"Unsupported autopilot action: {action}"
            return {"ok": False, "status": "error", "target_id": target, "steps": steps}
    return {"ok": True, "status": "max_steps", "target_id": target, "steps": steps}


class AgenticBrowserHandler(SimpleHTTPRequestHandler):
    server_version = "AgenticBrowserHTTP/1.0"

    def __init__(self, *args: Any, directory: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(SITE_ROOT), **kwargs)

    @property
    def browser_port(self) -> int:
        return int(self.server.browser_port)  # type: ignore[attr-defined]

    @property
    def model(self) -> str:
        return str(self.server.model)  # type: ignore[attr-defined]

    @property
    def reasoning_effort(self) -> str:
        return str(self.server.reasoning_effort)  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            self.send_json(
                {
                    "browser_port": self.browser_port,
                    "debug_url": debug_url(self.browser_port),
                    "targets": browser_targets(self.browser_port),
                    "action_log": str(ACTION_LOG),
                    "model": self.model,
                    "reasoning_effort": self.reasoning_effort,
                }
            )
            return
        if parsed.path == "/api/snapshot":
            query = urllib.parse.parse_qs(parsed.query)
            target_id = (query.get("target_id") or [""])[0] or None
            self.send_json(page_snapshot(self.browser_port, target_id))
            return
        if parsed.path == "/api/viewport":
            query = urllib.parse.parse_qs(parsed.query)
            target_id = (query.get("target_id") or [""])[0] or None
            quality = int((query.get("quality") or ["70"])[0] or 70)
            self.send_json(viewport_capture(self.browser_port, target_id, quality=quality))
            return
        super().do_GET()

    def do_POST(self) -> None:
        try:
            payload = self.read_json()
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/open":
                self.handle_open(payload)
                return
            if parsed.path == "/api/guarded-open":
                self.handle_guarded_open(payload)
                return
            if parsed.path == "/api/codex-decision":
                self.handle_codex_decision(payload)
                return
            if parsed.path == "/api/browser-action":
                self.handle_browser_action(payload)
                return
            if parsed.path == "/api/autopilot":
                self.handle_autopilot(payload)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def handle_open(self, payload: dict[str, Any]) -> None:
        url = normalize_url(str(payload.get("url") or ""))
        ensure_browser(self.browser_port)
        page = new_tab(self.browser_port, url)
        try:
            if payload.get("bring_to_front", True):
                page.bring_to_front()
        finally:
            page.close()
        append_action("open", {"url": url, "policy": host_policy(url)})
        self.send_json({"ok": True, "url": url, "policy": host_policy(url)})

    def handle_guarded_open(self, payload: dict[str, Any]) -> None:
        url = normalize_url(str(payload.get("url") or ""))
        policy = host_policy(url)
        if not policy["allowed"]:
            append_action("blocked_open", {"url": url, "policy": policy})
            self.send_json({"ok": False, "blocked": True, "url": url, "policy": policy}, status=HTTPStatus.FORBIDDEN)
            return
        ensure_browser(self.browser_port)
        page = new_tab(self.browser_port, url)
        try:
            page.bring_to_front()
        finally:
            page.close()
        append_action("guarded_open", {"url": url, "policy": policy})
        self.send_json({"ok": True, "url": url, "policy": policy})

    def handle_codex_decision(self, payload: dict[str, Any]) -> None:
        target_id = str(payload.get("target_id") or "") or None
        goal = str(payload.get("goal") or "")
        snapshot = page_snapshot(self.browser_port, target_id)
        decision = run_codex_decision(goal, snapshot, self.model, self.reasoning_effort)
        next_url = str(decision.get("next_url") or "").strip()
        if next_url:
            decision["next_url_policy"] = host_policy(next_url)
        append_action("codex_decision", {"goal": goal, "page_url": snapshot.get("url"), "decision": decision})
        self.send_json({"snapshot": snapshot, "decision": decision})

    def handle_browser_action(self, payload: dict[str, Any]) -> None:
        target_id = str(payload.get("target_id") or "") or None
        action = str(payload.get("action") or "")
        action_payload = dict(payload.get("payload") or {})
        result = browser_action(self.browser_port, target_id, action, action_payload)
        self.send_json(result)

    def handle_autopilot(self, payload: dict[str, Any]) -> None:
        target_id = str(payload.get("target_id") or "") or None
        goal = str(payload.get("goal") or "")
        max_steps = int(payload.get("max_steps") or 3)
        result = run_autopilot(
            self.browser_port,
            target_id,
            goal,
            max_steps,
            self.model,
            self.reasoning_effort,
        )
        self.send_json(result)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        data = self.rfile.read(length).decode("utf-8")
        return json.loads(data)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    args = parse_args()
    SITE_ROOT.mkdir(parents=True, exist_ok=True)
    ensure_chrome(args.browser_port, args.profile_dir, no_launch=False)
    server = ThreadingHTTPServer((args.host, args.port), AgenticBrowserHandler)
    server.browser_port = args.browser_port  # type: ignore[attr-defined]
    server.model = args.model  # type: ignore[attr-defined]
    server.reasoning_effort = args.reasoning_effort  # type: ignore[attr-defined]
    print(f"Agentic browser GUI: http://{args.host}:{args.port}")
    print(f"Controlled Chrome: {debug_url(args.browser_port)}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
