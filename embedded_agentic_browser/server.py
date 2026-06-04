#!/usr/bin/env python3
"""Embedded agentic browser GUI backed by Chrome DevTools Protocol."""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from dataclasses import asdict
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from embedded_agentic_browser.codex_aginti_wrapper import run_codex_decision
from embedded_agentic_browser.downloader import download_public_file
from embedded_agentic_browser.open_chrome_driver import DriverError, OpenChromeDriver, debug_url
from embedded_agentic_browser.safety import NavigationPolicy, classify_url, normalize_url


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = Path(__file__).resolve().parent
SITE_ROOT = PACKAGE_ROOT / "static"
DEFAULT_SERVER_PORT = 8791
DEFAULT_BROWSER_PORT = 9333
DEFAULT_PROFILE_DIR = Path.home() / ".cache" / "embedded-agentic-browser-chrome"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_REASONING_EFFORT = "low"
LOG_DIR = REPO_ROOT / "library" / "embedded-agentic-browser"
ACTION_LOG = LOG_DIR / "actions.jsonl"
DOWNLOAD_DIR = LOG_DIR / "downloads"
MAX_AUTOPILOT_STEPS = 8
RESULT_WAIT_TIMEOUT = 18.0


class EmbeddedBrowserError(RuntimeError):
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


def policy_dict_for_url(url: str) -> dict[str, Any]:
    if not url:
        return internal_policy("")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https", "file", ""}:
        return internal_policy(url)
    try:
        return classify_url(url).as_dict()
    except Exception as exc:
        return {
            "url": url,
            "host": parsed.netloc.lower(),
            "allowed": False,
            "mode": "invalid",
            "is_public_domain": False,
            "is_shadow_library": False,
            "is_design_tool": False,
            "looks_download": False,
            "looks_binary": False,
            "stop_reason": str(exc),
        }


def internal_policy(url: str) -> dict[str, Any]:
    return {
        "url": url,
        "host": "",
        "allowed": True,
        "mode": "browser-internal",
        "is_public_domain": False,
        "is_shadow_library": False,
        "is_design_tool": False,
        "looks_download": False,
        "looks_binary": False,
        "stop_reason": "",
    }


def target_to_dict(target: Any) -> dict[str, str]:
    return asdict(target)


def guard_navigation(url: str) -> NavigationPolicy:
    policy = classify_url(url)
    if not policy.allowed:
        append_action("blocked_navigation", {"url": policy.url, "policy": policy.as_dict()})
        raise EmbeddedBrowserError(policy.stop_reason)
    return policy


def libgen_search_url(query: str, collection: str = "libgen") -> str:
    value = " ".join((query or "").split())
    if not value:
        raise EmbeddedBrowserError("Book query is required")
    encoded_query = urllib.parse.quote(value)
    encoded_collection = urllib.parse.quote(collection or "libgen")
    return f"https://libgen.pw/search?query={encoded_query}&collection={encoded_collection}"


def default_book_goal(query: str, source: str) -> str:
    source_note = "LibGen search results" if source == "libgen" else "the current source"
    return (
        f"Search task: {query}. From {source_note}, choose the best valid book candidate. "
        "Prefer exact title, exact author, correct language, complete work, and reasonable file metadata. "
        "Finish with select or hold. Stop before mirror, download, direct-file, or access-control pages."
    )


def task_goal_with_source_boundary(query: str, source: str, goal: str) -> str:
    boundary = default_book_goal(query, source)
    if source == "libgen":
        boundary += (
            " This is a LibGen inspection validation: use visible LibGen search/detail evidence, "
            "finish by selecting or holding, and do not navigate away to another domain."
        )
    if not goal.strip():
        return boundary
    return f"{boundary}\nUser task details: {goal.strip()}"


def snapshot_with_policy(driver: OpenChromeDriver, target_id: str) -> dict[str, Any]:
    snapshot = driver.snapshot(target_id)
    snapshot["policy"] = policy_dict_for_url(str(snapshot.get("url") or ""))
    return snapshot


def is_expected_navigation(actual_url: str, expected_url: str) -> bool:
    actual = urllib.parse.urlparse(actual_url)
    expected = urllib.parse.urlparse(expected_url)
    if actual.scheme not in {"http", "https"}:
        return False
    if actual.netloc.lower() != expected.netloc.lower() or actual.path != expected.path:
        return False
    actual_query = urllib.parse.parse_qs(actual.query)
    expected_query = urllib.parse.parse_qs(expected.query)
    for key, values in expected_query.items():
        if actual_query.get(key) != values:
            return False
    return True


def wait_for_navigation(
    driver: OpenChromeDriver,
    target_id: str,
    expected_url: str,
    timeout: float = 12.0,
) -> dict[str, Any]:
    started = time.monotonic()
    snapshot = snapshot_with_policy(driver, target_id)
    while time.monotonic() - started < timeout:
        if is_expected_navigation(str(snapshot.get("url") or ""), expected_url):
            snapshot["navigation_state"] = {
                "ready": True,
                "waited_seconds": round(time.monotonic() - started, 2),
                "expected_url": expected_url,
            }
            return snapshot
        time.sleep(0.5)
        snapshot = snapshot_with_policy(driver, target_id)
    snapshot["navigation_state"] = {
        "ready": False,
        "waited_seconds": round(time.monotonic() - started, 2),
        "expected_url": expected_url,
    }
    return snapshot


def needs_dynamic_result_wait(snapshot: dict[str, Any]) -> bool:
    url = str(snapshot.get("url") or "")
    policy = snapshot.get("policy") or {}
    text = "\n".join(snapshot.get("textSample") or [])
    has_results = bool(snapshot.get("cards")) or bool(snapshot.get("downloadish")) or bool(snapshot.get("noResults"))
    is_shell = "Libgen" in text and "Search" in text and not has_results
    return bool(policy.get("is_shadow_library")) and "/search" in urllib.parse.urlparse(url).path and is_shell


def wait_for_dynamic_results(
    driver: OpenChromeDriver,
    target_id: str,
    first_snapshot: dict[str, Any] | None = None,
    timeout: float = RESULT_WAIT_TIMEOUT,
) -> dict[str, Any]:
    snapshot = first_snapshot or snapshot_with_policy(driver, target_id)
    if not needs_dynamic_result_wait(snapshot):
        snapshot["ready_state"] = {"ready": True, "waited_seconds": 0.0, "reason": "no_dynamic_wait_needed"}
        return snapshot

    started = time.monotonic()
    while time.monotonic() - started < timeout:
        time.sleep(0.75)
        snapshot = snapshot_with_policy(driver, target_id)
        if not needs_dynamic_result_wait(snapshot):
            snapshot["ready_state"] = {
                "ready": True,
                "waited_seconds": round(time.monotonic() - started, 2),
                "reason": "dynamic_results_visible",
            }
            return snapshot

    snapshot["ready_state"] = {
        "ready": False,
        "waited_seconds": round(time.monotonic() - started, 2),
        "reason": "timed_out_waiting_for_dynamic_results",
    }
    return snapshot


def observe_page(driver: OpenChromeDriver, target_id: str | None, quality: int = 74) -> dict[str, Any]:
    snapshot = snapshot_with_policy(driver, driver.target(target_id).id)
    capture = driver.capture(str(snapshot["target_id"]), quality=quality)
    capture["policy"] = policy_dict_for_url(str((capture.get("metrics") or {}).get("url") or ""))
    return {
        "target_id": snapshot["target_id"],
        "snapshot": snapshot,
        "viewport": capture,
    }


def run_autopilot(
    driver: OpenChromeDriver,
    target_id: str | None,
    goal: str,
    max_steps: int,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    target = driver.target(target_id)
    for step_index in range(1, min(max_steps, MAX_AUTOPILOT_STEPS) + 1):
        snapshot = wait_for_dynamic_results(driver, target.id)
        decision = run_codex_decision(goal, snapshot, step_index, model, reasoning_effort)
        next_url = str(decision.get("next_url") or "").strip()
        if next_url:
            decision["next_url_policy"] = policy_dict_for_url(next_url)
        step_record = {
            "step": step_index,
            "page_url": snapshot.get("url"),
            "page_title": snapshot.get("title"),
            "decision": decision,
        }
        steps.append(step_record)
        append_action("aginti_decision", {"goal": goal, **step_record})

        action = str(decision.get("action") or "")
        if action in {"select", "hold", "stop"} or decision.get("safety_stop"):
            return {"ok": True, "status": action or "stop", "target_id": target.id, "steps": steps}
        if action == "open_url":
            if not next_url:
                step_record["error"] = "open_url action had empty next_url"
                return {"ok": False, "status": "error", "target_id": target.id, "steps": steps}
            policy = classify_url(next_url)
            if not policy.allowed:
                step_record["blocked"] = policy.as_dict()
                append_action("autopilot_blocked", {"url": policy.url, "policy": policy.as_dict()})
                return {"ok": False, "status": "blocked", "target_id": target.id, "steps": steps}
            driver.action(target.id, "navigate", {"url": policy.url})
            time.sleep(2.0)
        elif action == "scroll":
            delta = int(decision.get("scroll_delta_y") or 700)
            driver.action(target.id, "scroll", {"delta_y": delta})
            time.sleep(0.7)
        elif action == "wait":
            seconds = max(0.1, min(10.0, float(decision.get("wait_seconds") or 1.0)))
            driver.action(target.id, "wait", {"seconds": seconds})
        else:
            step_record["error"] = f"Unsupported autopilot action: {action}"
            return {"ok": False, "status": "error", "target_id": target.id, "steps": steps}
    return {"ok": True, "status": "max_steps", "target_id": target.id, "steps": steps}


def run_book_task(
    driver: OpenChromeDriver,
    query: str,
    source: str,
    goal: str,
    max_steps: int,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    normalized_source = (source or "libgen").strip().lower()
    if normalized_source != "libgen":
        raise EmbeddedBrowserError(f"Unsupported book task source: {source}")

    url = libgen_search_url(query)
    policy = guard_navigation(url)
    target = driver.new_tab(policy.url)
    page = driver.page(target.id)
    try:
        page.bring_to_front()
    finally:
        page.close()

    append_action("book_task_open", {"query": query, "source": normalized_source, "url": policy.url, "policy": policy.as_dict()})
    navigated_snapshot = wait_for_navigation(driver, target.id, policy.url)
    initial_snapshot = wait_for_dynamic_results(driver, target.id, first_snapshot=navigated_snapshot)
    task_goal = task_goal_with_source_boundary(query, normalized_source, goal)
    result = run_autopilot(driver, target.id, task_goal, max_steps, model, reasoning_effort)
    append_action(
        "book_task_result",
        {
            "query": query,
            "source": normalized_source,
            "target_id": target.id,
            "status": result.get("status"),
            "steps": len(result.get("steps") or []),
        },
    )
    return {
        "ok": bool(result.get("ok", False)),
        "query": query,
        "source": normalized_source,
        "url": policy.url,
        "target": target_to_dict(target),
        "initial_snapshot": initial_snapshot,
        "result": result,
    }


def libgen_inspection_start_url(value: str) -> str:
    raw = " ".join((value or "").split())
    if not raw:
        raise EmbeddedBrowserError("LibGen query or URL is required")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme:
        return raw
    return libgen_search_url(raw)


def wait_for_links_page(driver: OpenChromeDriver, target_id: str, timeout: float = 10.0) -> dict[str, Any]:
    started = time.monotonic()
    snapshot = snapshot_with_policy(driver, target_id)
    while time.monotonic() - started < timeout:
        path = urllib.parse.urlparse(str(snapshot.get("url") or "")).path
        text = "\n".join(snapshot.get("textSample") or [])
        mirror_link_visible = any(
            str(link.get("text") or "").strip().lower() in {"libgen", "annas-archive"}
            for link in snapshot.get("links") or []
        )
        has_visible_mirror_area = "Get" in text or mirror_link_visible
        if path.startswith("/links") and has_visible_mirror_area:
            snapshot["ready_state"] = {
                "ready": True,
                "waited_seconds": round(time.monotonic() - started, 2),
                "reason": "links_page_visible",
            }
            return snapshot
        time.sleep(0.5)
        snapshot = snapshot_with_policy(driver, target_id)
    snapshot["ready_state"] = {
        "ready": False,
        "waited_seconds": round(time.monotonic() - started, 2),
        "reason": "timed_out_waiting_for_links_page",
    }
    return snapshot


def classify_snapshot_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    classified: list[dict[str, Any]] = []
    for link in links:
        href = str(link.get("href") or "")
        if not href.startswith(("http://", "https://")):
            continue
        policy = policy_dict_for_url(href)
        if policy.get("is_shadow_library") or policy.get("looks_download"):
            classified.append({**link, "policy": policy})
    return classified


def open_libgen_link_inspection(
    driver: OpenChromeDriver,
    query_or_url: str,
    goal: str,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    start_url = libgen_inspection_start_url(query_or_url)
    policy = guard_navigation(start_url)
    target = driver.new_tab(policy.url)
    page = driver.page(target.id)
    try:
        page.bring_to_front()
    finally:
        page.close()

    append_action("libgen_inspect_open", {"query_or_url": query_or_url, "url": policy.url, "policy": policy.as_dict()})
    navigated_snapshot = wait_for_navigation(driver, target.id, policy.url)
    snapshot = wait_for_dynamic_results(driver, target.id, first_snapshot=navigated_snapshot)
    path = urllib.parse.urlparse(str(snapshot.get("url") or "")).path
    selected_card: dict[str, Any] | None = None
    decision: dict[str, Any] = {}
    inspection_steps: list[dict[str, Any]] = []

    if path.startswith("/links"):
        links_snapshot = snapshot
    else:
        if path.startswith("/search"):
            inspect_goal = (
                "Select the best visible LibGen candidate for inspection only. "
                "Prefer the top-ranked exact search result when it already matches the requested author, language, and format. "
                "Prefer exact title, exact author, Japanese language if relevant, epub over other formats when otherwise equal. "
                "Do not prefer a later year or smaller file unless the title/author/language match is clearly better. "
                "Do not choose mirror/download pages. Finish with select or hold."
            )
            if goal.strip():
                inspect_goal += "\nUser task details: " + goal.strip()
            for step_index in range(1, 4):
                decision = run_codex_decision(inspect_goal, snapshot, step_index, model, reasoning_effort)
                action = str(decision.get("action") or "hold")
                inspection_steps.append(
                    {
                        "step": step_index,
                        "action": action,
                        "page_url": snapshot.get("url"),
                        "cards": len(snapshot.get("cards") or []),
                        "reason": decision.get("reason"),
                    }
                )
                if action == "select" and decision.get("selected_index") is not None:
                    break
                if action == "scroll":
                    delta = int(decision.get("scroll_delta_y") or 700)
                    driver.action(target.id, "scroll", {"delta_y": delta})
                    time.sleep(0.7)
                    snapshot = wait_for_dynamic_results(driver, target.id)
                    continue
                if action == "wait":
                    seconds = max(0.1, min(10.0, float(decision.get("wait_seconds") or 1.0)))
                    driver.action(target.id, "wait", {"seconds": seconds})
                    snapshot = wait_for_dynamic_results(driver, target.id)
                    continue
                return {
                    "ok": True,
                    "status": action,
                    "target": target_to_dict(target),
                    "start_url": policy.url,
                    "initial_snapshot": snapshot,
                    "inspection_steps": inspection_steps,
                    "decision": decision,
                    "links_snapshot": None,
                    "mirror_links": [],
                }
            else:
                return {
                    "ok": True,
                    "status": "max_inspection_steps",
                    "target": target_to_dict(target),
                    "start_url": policy.url,
                    "initial_snapshot": snapshot,
                    "inspection_steps": inspection_steps,
                    "decision": decision,
                    "links_snapshot": None,
                    "mirror_links": [],
                }
            if str(decision.get("action") or "") != "select" or decision.get("selected_index") is None:
                return {
                    "ok": True,
                    "status": str(decision.get("action") or "hold"),
                    "target": target_to_dict(target),
                    "start_url": policy.url,
                    "initial_snapshot": snapshot,
                    "inspection_steps": inspection_steps,
                    "decision": decision,
                    "links_snapshot": None,
                    "mirror_links": [],
                }
            selected_index = int(decision["selected_index"])
            cards = snapshot.get("cards") or []
            if selected_index < 0 or selected_index >= len(cards):
                raise EmbeddedBrowserError(f"Selected card index out of range: {selected_index}")
            selected_card = dict(cards[selected_index])
            selector = str(selected_card.get("file_selector") or "")
            if not selector:
                raise EmbeddedBrowserError("Selected card does not expose a file selector")
            driver.action(target.id, "click_selector", {"selector": selector})
            links_snapshot = wait_for_links_page(driver, target.id)
        elif path.startswith("/book"):
            cards = snapshot.get("cards") or []
            selector = ""
            if cards:
                selected_card = dict(cards[0])
                selector = str(selected_card.get("file_selector") or "")
            if not selector:
                for element in snapshot.get("interactive") or []:
                    if "v-book-card__link" in str(element.get("selector") or ""):
                        selector = str(element.get("selector") or "")
                        break
            if not selector:
                book_id = path.rstrip("/").split("/")[-1]
                if not book_id:
                    raise EmbeddedBrowserError("Book detail page does not expose a file selector")
                links_url = f"https://libgen.pw/links/{urllib.parse.quote(book_id)}"
                links_policy = guard_navigation(links_url)
                driver.action(target.id, "navigate", {"url": links_policy.url})
            else:
                driver.action(target.id, "click_selector", {"selector": selector})
            links_snapshot = wait_for_links_page(driver, target.id)
        else:
            raise EmbeddedBrowserError(f"Unsupported LibGen inspection page: {snapshot.get('url')}")

    mirror_links = classify_snapshot_links(links_snapshot.get("links") or [])
    append_action(
        "libgen_inspect_result",
        {
            "query_or_url": query_or_url,
            "target_id": target.id,
            "status": "links_ready",
            "links_url": links_snapshot.get("url"),
            "selected_card": selected_card,
            "mirror_links": len(mirror_links),
        },
    )
    return {
        "ok": True,
        "status": "links_ready",
        "target": target_to_dict(target),
        "start_url": policy.url,
        "initial_snapshot": snapshot,
        "inspection_steps": inspection_steps,
        "decision": decision,
        "selected_card": selected_card,
        "links_snapshot": links_snapshot,
        "mirror_links": mirror_links,
        "stop_reason": "Stopped at LibGen links inspection page before mirror/download navigation.",
    }


class EmbeddedBrowserHandler(SimpleHTTPRequestHandler):
    server_version = "EmbeddedAgenticBrowserHTTP/1.0"

    def __init__(self, *args: Any, directory: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(SITE_ROOT), **kwargs)

    @property
    def driver(self) -> OpenChromeDriver:
        return self.server.driver  # type: ignore[attr-defined]

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
                    "browser_port": self.driver.port,
                    "debug_url": debug_url(self.driver.port),
                    "targets": [target_to_dict(target) for target in self.driver.targets()],
                    "action_log": str(ACTION_LOG),
                    "model": self.model,
                    "reasoning_effort": self.reasoning_effort,
                }
            )
            return
        if parsed.path == "/api/snapshot":
            query = urllib.parse.parse_qs(parsed.query)
            target_id = (query.get("target_id") or [""])[0] or None
            snapshot = self.driver.snapshot(target_id)
            snapshot["policy"] = policy_dict_for_url(str(snapshot.get("url") or ""))
            self.send_json(snapshot)
            return
        if parsed.path == "/api/viewport":
            query = urllib.parse.parse_qs(parsed.query)
            target_id = (query.get("target_id") or [""])[0] or None
            quality = int((query.get("quality") or ["72"])[0] or 72)
            capture = self.driver.capture(target_id, quality=quality)
            capture["policy"] = policy_dict_for_url(str((capture.get("metrics") or {}).get("url") or ""))
            self.send_json(capture)
            return
        if parsed.path == "/api/observe":
            query = urllib.parse.parse_qs(parsed.query)
            target_id = (query.get("target_id") or [""])[0] or None
            quality = int((query.get("quality") or ["74"])[0] or 74)
            self.send_json(observe_page(self.driver, target_id, quality=quality))
            return
        super().do_GET()

    def do_POST(self) -> None:
        try:
            payload = self.read_json()
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/open":
                self.handle_open(payload, guarded=False)
                return
            if parsed.path == "/api/guarded-open":
                self.handle_open(payload, guarded=True)
                return
            if parsed.path in {"/api/action", "/api/browser-action"}:
                self.handle_action(payload)
                return
            if parsed.path in {"/api/agent-step", "/api/codex-decision"}:
                self.handle_agent_step(payload)
                return
            if parsed.path == "/api/autopilot":
                self.handle_autopilot(payload)
                return
            if parsed.path == "/api/run-book-task":
                self.handle_run_book_task(payload)
                return
            if parsed.path == "/api/libgen-inspect":
                self.handle_libgen_inspect(payload)
                return
            if parsed.path == "/api/autonomous-run":
                self.handle_autonomous_run(payload)
                return
            if parsed.path == "/api/download":
                self.handle_download(payload)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def handle_open(self, payload: dict[str, Any], guarded: bool) -> None:
        url = normalize_url(str(payload.get("url") or ""))
        policy = classify_url(url)
        if guarded and not policy.allowed:
            append_action("blocked_open", {"url": policy.url, "policy": policy.as_dict()})
            self.send_json({"ok": False, "blocked": True, "url": policy.url, "policy": policy.as_dict()}, HTTPStatus.FORBIDDEN)
            return
        target = self.driver.new_tab(policy.url)
        if payload.get("bring_to_front", True):
            page = self.driver.page(target.id)
            try:
                page.bring_to_front()
            finally:
                page.close()
        append_action("guarded_open" if guarded else "open", {"url": policy.url, "policy": policy.as_dict()})
        self.send_json({"ok": True, "target": target_to_dict(target), "url": policy.url, "policy": policy.as_dict()})

    def handle_action(self, payload: dict[str, Any]) -> None:
        target_id = str(payload.get("target_id") or "") or None
        action = str(payload.get("action") or "")
        action_payload = dict(payload.get("payload") or {})
        if action == "navigate":
            policy = guard_navigation(str(action_payload.get("url") or ""))
            action_payload["url"] = policy.url
        result = self.driver.action(target_id, action, action_payload)
        append_action("browser_action", {"target_id": result.get("target_id"), "action": action, "payload": action_payload, "result": result})
        self.send_json(result)

    def handle_agent_step(self, payload: dict[str, Any]) -> None:
        target_id = str(payload.get("target_id") or "") or None
        goal = str(payload.get("goal") or "")
        snapshot = self.driver.snapshot(target_id)
        snapshot["policy"] = policy_dict_for_url(str(snapshot.get("url") or ""))
        decision = run_codex_decision(goal, snapshot, 1, self.model, self.reasoning_effort)
        next_url = str(decision.get("next_url") or "").strip()
        if next_url:
            decision["next_url_policy"] = policy_dict_for_url(next_url)
        append_action("agent_step", {"goal": goal, "page_url": snapshot.get("url"), "decision": decision})
        self.send_json({"snapshot": snapshot, "decision": decision})

    def handle_autopilot(self, payload: dict[str, Any]) -> None:
        target_id = str(payload.get("target_id") or "") or None
        goal = str(payload.get("goal") or "")
        max_steps = int(payload.get("max_steps") or 3)
        result = run_autopilot(self.driver, target_id, goal, max_steps, self.model, self.reasoning_effort)
        self.send_json(result)

    def handle_run_book_task(self, payload: dict[str, Any]) -> None:
        query = str(payload.get("query") or "")
        source = str(payload.get("source") or "libgen")
        goal = str(payload.get("goal") or "")
        max_steps = int(payload.get("max_steps") or 3)
        result = run_book_task(self.driver, query, source, goal, max_steps, self.model, self.reasoning_effort)
        self.send_json(result)

    def handle_libgen_inspect(self, payload: dict[str, Any]) -> None:
        query_or_url = str(payload.get("query_or_url") or payload.get("query") or payload.get("url") or "")
        goal = str(payload.get("goal") or "")
        result = open_libgen_link_inspection(self.driver, query_or_url, goal, self.model, self.reasoning_effort)
        self.send_json(result)

    def handle_autonomous_run(self, payload: dict[str, Any]) -> None:
        from embedded_agentic_browser.agent import AgentRunConfig, run_agent

        goal = str(payload.get("goal") or "")
        start_url = str(payload.get("start_url") or "")
        target_id = str(payload.get("target_id") or "") or None
        max_steps = int(payload.get("max_steps") or 8)
        if not goal.strip():
            raise EmbeddedBrowserError("Autonomous goal is required")
        result = run_agent(
            AgentRunConfig(
                goal=goal,
                start_url=start_url,
                target_id=target_id,
                max_steps=max_steps,
                model=self.model,
                reasoning_effort=self.reasoning_effort,
                browser_port=self.driver.port,
                profile_dir=self.driver.profile_dir,
                log_dir=LOG_DIR / "agent-runs",
                download_dir=DOWNLOAD_DIR,
                make_plan=bool(payload.get("make_plan", True)),
            )
        )
        append_action(
            "autonomous_run",
            {
                "goal": goal,
                "start_url": start_url,
                "target_id": result.get("target_id"),
                "status": result.get("status"),
                "steps": result.get("steps"),
                "log_path": result.get("log_path"),
            },
        )
        self.send_json(result)

    def handle_download(self, payload: dict[str, Any]) -> None:
        url = str(payload.get("url") or "")
        filename = str(payload.get("filename") or "")
        result = download_public_file(url, DOWNLOAD_DIR, requested_filename=filename)
        append_action("download", result)
        self.send_json(result)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

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
    driver = OpenChromeDriver(args.browser_port, args.profile_dir)
    server = ThreadingHTTPServer((args.host, args.port), EmbeddedBrowserHandler)
    server.driver = driver  # type: ignore[attr-defined]
    server.model = args.model  # type: ignore[attr-defined]
    server.reasoning_effort = args.reasoning_effort  # type: ignore[attr-defined]
    print(f"Embedded agentic browser: http://{args.host}:{args.port}")
    print(f"Controlled Chrome CDP: {debug_url(args.browser_port)}")
    print(f"Codex wrapper: {args.model} / {args.reasoning_effort}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except DriverError as exc:
        raise EmbeddedBrowserError(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
