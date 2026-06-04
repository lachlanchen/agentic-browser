"""Small open Chrome/Chromium driver backed by Chrome DevTools Protocol."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websocket


HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    )
}


class DriverError(RuntimeError):
    pass


def debug_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def find_chrome_binary() -> str:
    preferred = os.environ.get("OPEN_CHROME_BIN", "")
    candidates = [preferred] if preferred else []
    candidates.extend(["chromium", "chromium-browser", "google-chrome"])
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise DriverError("No Chrome/Chromium binary found. Set OPEN_CHROME_BIN if needed.")


def request_json(base_url: str, path: str, method: str = "GET") -> Any:
    request = urllib.request.Request(base_url + path, method=method, headers=HTTP_HEADERS)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def is_alive(port: int) -> bool:
    try:
        request_json(debug_url(port), "/json/version")
        return True
    except Exception:
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
    profile_dir.mkdir(parents=True, exist_ok=True)
    remove_stale_singletons(profile_dir)
    binary = find_chrome_binary()
    extra_args = shlex.split(os.environ.get("EMBEDDED_AGENTIC_CHROME_ARGS", ""))
    command = [
        binary,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-allow-origins={debug_url(port)}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        *extra_args,
        "--new-window",
        "about:blank",
    ]
    log_path = Path("/tmp/embedded_agentic_browser_chrome.log")
    handle = log_path.open("ab")
    subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)


def ensure_chrome(port: int, profile_dir: Path) -> None:
    if is_alive(port):
        return
    launch_chrome(port, profile_dir.expanduser())
    deadline = time.time() + 30
    while time.time() < deadline:
        if is_alive(port):
            return
        time.sleep(0.5)
    raise DriverError(f"Chrome DevTools did not become available at {debug_url(port)}")


@dataclass
class Target:
    id: str
    title: str
    url: str
    websocket_url: str


class CDPPage:
    def __init__(self, websocket_url: str, origin: str) -> None:
        self.ws = websocket.create_connection(websocket_url, timeout=35, origin=origin)
        self._id = 0
        for method in ("Runtime.enable", "Page.enable"):
            try:
                self.call(method)
            except websocket.WebSocketTimeoutException:
                # Busy pages can delay enable responses; direct commands often still work.
                continue

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
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        result = response.get("result", {})
        if "exceptionDetails" in result:
            raise DriverError(json.dumps(result["exceptionDetails"], ensure_ascii=False, indent=2))
        return result.get("result", {}).get("value")

    def bring_to_front(self) -> None:
        self.call("Page.bringToFront")


class OpenChromeDriver:
    def __init__(self, port: int, profile_dir: Path) -> None:
        self.port = port
        self.profile_dir = profile_dir
        ensure_chrome(port, profile_dir)

    @property
    def base_url(self) -> str:
        return debug_url(self.port)

    def targets(self) -> list[Target]:
        payload = request_json(self.base_url, "/json/list")
        targets = []
        for item in payload:
            if item.get("type") != "page":
                continue
            targets.append(
                Target(
                    id=str(item.get("id")),
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    websocket_url=str(item.get("webSocketDebuggerUrl") or ""),
                )
            )
        return targets

    def new_tab(self, url: str) -> Target:
        encoded = urllib.parse.quote(url, safe="")
        try:
            payload = request_json(self.base_url, f"/json/new?{encoded}", method="PUT")
        except urllib.error.HTTPError:
            payload = request_json(self.base_url, f"/json/new?{encoded}", method="GET")
        return Target(
            id=str(payload["id"]),
            title=str(payload.get("title") or ""),
            url=str(payload.get("url") or url),
            websocket_url=str(payload["webSocketDebuggerUrl"]),
        )

    def target(self, target_id: str | None = None) -> Target:
        targets = self.targets()
        if not targets:
            raise DriverError("No Chrome targets available")
        if target_id:
            for target in targets:
                if target.id == target_id:
                    return target
            raise DriverError(f"Target not found: {target_id}")
        return targets[0]

    def page(self, target_id: str | None = None) -> CDPPage:
        target = self.target(target_id)
        return CDPPage(target.websocket_url, origin=self.base_url)

    def snapshot(self, target_id: str | None = None) -> dict[str, Any]:
        target = self.target(target_id)
        page = self.page(target.id)
        try:
            snapshot = page.evaluate(
                r"""
(() => {
  const text = document.body ? document.body.innerText : "";
  const lines = text.split("\n").map(x => x.trim()).filter(Boolean);
  const pick = (root, sel) => (root.querySelector(sel)?.innerText || "").trim();
  const esc = (value) => window.CSS && CSS.escape ? CSS.escape(value) : String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  const visible = (el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
  };
  const cssPath = (el) => {
    if (el.id) return `#${esc(el.id)}`;
    const stableClasses = (node) => [...node.classList]
      .filter(c => !/^fade-(enter|leave)-/.test(c))
      .slice(0, 2);
    const parts = [];
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE && parts.length < 5) {
      let part = node.tagName.toLowerCase();
      const classes = stableClasses(node).map(c => `.${esc(c)}`).join("");
      if (classes) part += classes;
      const parent = node.parentElement;
      if (parent) {
        const siblings = [...parent.children].filter(x => x.tagName === node.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      node = parent;
    }
    return parts.join(" > ");
  };
  const elementText = (el) => (
    el.innerText ||
    el.value ||
    el.getAttribute("aria-label") ||
    el.getAttribute("title") ||
    el.getAttribute("placeholder") ||
    ""
  ).trim();
  const cards = [...document.querySelectorAll(".v-book-card")].map((card, index) => {
    const fileEl = card.querySelector(".v-book-card__link");
    return {
      index,
      title: pick(card, ".v-book-card__title"),
      authors: [...card.querySelectorAll(".v-book-card__author")].map(x => x.innerText.trim()).filter(Boolean),
      year: pick(card, ".v-book-card__year"),
      lang: pick(card, ".v-book-card__lang"),
      file: pick(card, ".v-book-card__link"),
      selector: cssPath(card),
      file_selector: fileEl ? cssPath(fileEl) : "",
      text: card.innerText.trim().slice(0, 900)
    };
  }).slice(0, 80);
  const links = [...document.querySelectorAll("a[href]")].map((a, index) => ({
    index,
    text: (a.innerText || a.textContent || a.getAttribute("title") || "").trim().slice(0, 220),
    href: a.href
  })).filter(x => x.href).slice(0, 240);
  const downloadish = links.filter(x => /download|pdf|epub|mobi|azw|djvu|zip|rar|下載|下载/i.test(`${x.text} ${x.href}`)).slice(0, 100);
  const interactiveSelector = [
    "a[href]",
    "button",
    "input",
    "textarea",
    "select",
    "[role=button]",
    "[contenteditable=true]",
    "[onclick]",
    ".v-book-card__link",
    ".v-search-input__button"
  ].join(",");
  const interactive = [...document.querySelectorAll(interactiveSelector)]
    .filter(visible)
    .map((el, index) => ({
      index,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || "",
      text: elementText(el).slice(0, 220),
      href: el.href || "",
      selector: cssPath(el),
      name: el.getAttribute("name") || "",
      role: el.getAttribute("role") || "",
      placeholder: el.getAttribute("placeholder") || "",
      value: (el.value || "").slice(0, 120),
      disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true")
    }))
    .slice(0, 160);
  return {
    title: document.title,
    url: location.href,
    noResults: /no results found/i.test(text),
    cards,
    links,
    downloadish,
    interactive,
    textSample: lines.slice(0, 100),
    scroll: {x: window.scrollX, y: window.scrollY, height: document.body ? document.body.scrollHeight : 0},
    viewport: {width: window.innerWidth, height: window.innerHeight, devicePixelRatio: window.devicePixelRatio}
  };
})()
"""
            )
        finally:
            page.close()
        snapshot["target_id"] = target.id
        return snapshot

    def capture(self, target_id: str | None = None, quality: int = 72) -> dict[str, Any]:
        target = self.target(target_id)
        page = self.page(target.id)
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
                raise DriverError(str(response["error"]))
            data = response.get("result", {}).get("data", "")
        finally:
            page.close()
        return {"target_id": target.id, "metrics": metrics, "screenshot": f"data:image/jpeg;base64,{data}"}

    def action(self, target_id: str | None, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        target = self.target(target_id)
        page = self.page(target.id)
        try:
            page.bring_to_front()
            if action == "click":
                x = float(payload.get("x") or 0)
                y = float(payload.get("y") or 0)
                for event_type in ("mousePressed", "mouseReleased"):
                    page.call(
                        "Input.dispatchMouseEvent",
                        {"type": event_type, "x": x, "y": y, "button": "left", "clickCount": 1},
                    )
                result = {"clicked": {"x": x, "y": y}}
            elif action == "click_selector":
                selector = str(payload.get("selector") or "")
                if not selector:
                    raise DriverError("click_selector requires selector")
                hit = page.evaluate(
                    f"""
(() => {{
  const selector = {json.dumps(selector)};
  const el = document.querySelector(selector);
  if (!el) return {{found: false, selector}};
  el.scrollIntoView({{block: "center", inline: "center"}});
  const rect = el.getBoundingClientRect();
  if (!rect.width || !rect.height) return {{found: false, selector, reason: "element has empty bounding box"}};
  if (el.disabled || el.getAttribute("aria-disabled") === "true") return {{found: false, selector, reason: "element disabled"}};
  if (el.focus) el.focus({{preventScroll: true}});
  return {{
    found: true,
    selector,
    text: (el.innerText || el.value || el.getAttribute("aria-label") || "").trim().slice(0, 220),
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2
  }};
}})()
"""
                )
                if not hit or not hit.get("found"):
                    raise DriverError(f"Selector not clickable: {hit}")
                for event_type in ("mousePressed", "mouseReleased"):
                    page.call(
                        "Input.dispatchMouseEvent",
                        {"type": event_type, "x": float(hit["x"]), "y": float(hit["y"]), "button": "left", "clickCount": 1},
                    )
                result = {"clicked_selector": hit}
            elif action == "click_text":
                text = str(payload.get("text") or "").strip()
                if not text:
                    raise DriverError("click_text requires text")
                hit = page.evaluate(
                    f"""
(() => {{
  const needle = {json.dumps(text)}.toLowerCase();
  const norm = (value) => String(value || "").replace(/\\s+/g, " ").trim().toLowerCase();
  const visible = (el) => {{
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
  }};
  const candidates = [...document.querySelectorAll("a[href],button,input[type=button],input[type=submit],[role=button],[onclick],.v-search-input__button")].filter(visible);
  const el = candidates.find(x => norm(x.innerText || x.value || x.getAttribute("aria-label") || x.getAttribute("title")).includes(needle));
  if (!el) return {{found: false, text: needle, candidates: candidates.slice(0, 20).map(x => norm(x.innerText || x.value || x.getAttribute("aria-label") || x.getAttribute("title")))}};
  el.scrollIntoView({{block: "center", inline: "center"}});
  const rect = el.getBoundingClientRect();
  if (el.focus) el.focus({{preventScroll: true}});
  return {{
    found: true,
    text: (el.innerText || el.value || el.getAttribute("aria-label") || "").trim().slice(0, 220),
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2
  }};
}})()
"""
                )
                if not hit or not hit.get("found"):
                    raise DriverError(f"Text target not clickable: {hit}")
                for event_type in ("mousePressed", "mouseReleased"):
                    page.call(
                        "Input.dispatchMouseEvent",
                        {"type": event_type, "x": float(hit["x"]), "y": float(hit["y"]), "button": "left", "clickCount": 1},
                    )
                result = {"clicked_text": hit}
            elif action == "scroll":
                delta_y = int(payload.get("delta_y") or 700)
                page.evaluate(f"window.scrollBy(0, {delta_y}); true;")
                result = {"scrolled": delta_y}
            elif action == "type":
                text = str(payload.get("text") or "")
                page.call("Input.insertText", {"text": text})
                result = {"typed_length": len(text)}
            elif action == "type_selector":
                selector = str(payload.get("selector") or "")
                text = str(payload.get("text") or "")
                clear_first = bool(payload.get("clear_first", True))
                if not selector:
                    raise DriverError("type_selector requires selector")
                target_info = page.evaluate(
                    f"""
(() => {{
  const selector = {json.dumps(selector)};
  const clearFirst = {json.dumps(clear_first)};
  const el = document.querySelector(selector);
  if (!el) return {{found: false, selector}};
  el.scrollIntoView({{block: "center", inline: "center"}});
  if (el.focus) el.focus({{preventScroll: true}});
  if (clearFirst) {{
    if (el.isContentEditable) {{
      el.textContent = "";
    }} else if ("value" in el) {{
      el.value = "";
    }}
    el.dispatchEvent(new Event("input", {{bubbles: true}}));
    el.dispatchEvent(new Event("change", {{bubbles: true}}));
  }}
  const rect = el.getBoundingClientRect();
  return {{
    found: true,
    selector,
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute("type") || "",
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2
  }};
}})()
"""
                )
                if not target_info or not target_info.get("found"):
                    raise DriverError(f"Selector not typeable: {target_info}")
                page.call("Input.insertText", {"text": text})
                page.evaluate(
                    """
(() => {
  const el = document.activeElement;
  if (el) {
    el.dispatchEvent(new Event("input", {bubbles: true}));
    el.dispatchEvent(new Event("change", {bubbles: true}));
  }
  return true;
})()
"""
                )
                result = {"typed_selector": target_info, "typed_length": len(text), "clear_first": clear_first}
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
                url = str(payload.get("url") or "")
                try:
                    page.call("Page.navigate", {"url": url})
                    result = {"navigated": url, "timed_out": False}
                except websocket.WebSocketTimeoutException:
                    # Navigation can continue while the CDP response is delayed by a busy page.
                    result = {"navigated": url, "timed_out": True}
            elif action == "wait":
                seconds = max(0.1, min(10.0, float(payload.get("seconds") or 1.0)))
                time.sleep(seconds)
                result = {"waited": seconds}
            else:
                raise DriverError(f"Unsupported action: {action}")
        finally:
            page.close()
        return {"ok": True, "target_id": target.id, "action": action, "result": result}
