#!/usr/bin/env python3
"""CLI client for the embedded agentic browser service."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_URL = os.environ.get("AGENTIC_BROWSER_URL", "http://127.0.0.1:8794")
VDESKTOP_SCRIPT = REPO_ROOT / "run-agentic-browser-vdesktop.sh"


class CliError(RuntimeError):
    pass


class BrowserClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 240.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        url = self.base_url + path
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw)
                detail = body.get("error") or body.get("policy", {}).get("stop_reason") or raw
            except Exception:
                detail = raw or str(exc)
            raise CliError(f"HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise CliError(f"Cannot reach {url}: {exc}") from exc
        if not raw.strip():
            return {}
        return json.loads(raw)

    def get(self, path: str, timeout: float | None = None) -> Any:
        return self.request("GET", path, timeout=timeout)

    def post(self, path: str, payload: dict[str, Any], timeout: float | None = None) -> Any:
        return self.request("POST", path, payload, timeout=timeout)


def compact(value: str, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def status_summary(data: dict[str, Any]) -> str:
    lines = [
        f"service: ok",
        f"browser_port: {data.get('browser_port')}",
        f"model: {data.get('model')} / {data.get('reasoning_effort')}",
        f"targets: {len(data.get('targets') or [])}",
    ]
    targets = data.get("targets") or []
    for index, target in enumerate(targets[:8], 1):
        lines.append(f"{index}. {target.get('id')} | {compact(target.get('title') or '(untitled)', 60)} | {compact(target.get('url'), 90)}")
    return "\n".join(lines)


def observe_summary(data: dict[str, Any]) -> str:
    snapshot = data.get("snapshot") or data
    policy = snapshot.get("policy") or {}
    lines = [
        f"title: {snapshot.get('title') or '(untitled)'}",
        f"url: {snapshot.get('url')}",
        f"policy: {policy.get('mode') or 'regular'} {'allowed' if policy.get('allowed', True) else 'blocked'}",
        f"interactive: {len(snapshot.get('interactive') or [])}",
        f"cards: {len(snapshot.get('cards') or [])}",
        f"downloadish: {len(snapshot.get('downloadish') or [])}",
    ]
    for card in (snapshot.get("cards") or [])[:6]:
        lines.append(
            f"card {card.get('index')}: {compact(card.get('title'), 70)} | "
            f"{compact('; '.join(card.get('authors') or []), 50)} | {card.get('lang') or ''} | {card.get('file') or ''}"
        )
    return "\n".join(lines)


def autonomous_summary(data: dict[str, Any]) -> str:
    lines = [
        f"status: {data.get('status')}",
        f"run_id: {data.get('run_id')}",
        f"steps: {data.get('steps')}",
        f"target_id: {data.get('target_id')}",
        f"log: {data.get('log_path')}",
    ]
    plan = data.get("plan") or {}
    if plan.get("plan"):
        lines.append("plan:")
        for index, step in enumerate(plan.get("plan") or [], 1):
            lines.append(f"  {index}. {step}")
    final = data.get("final_decision") or {}
    if final:
        lines.append(f"final: {final.get('action')} - {final.get('reason')}")
        if final.get("url"):
            lines.append(f"url: {final.get('url')}")
    last = (data.get("step_records") or [{}])[-1].get("execution") or {}
    if last:
        lines.append(f"execution: {last.get('status')}")
        result = last.get("result") or {}
        if result.get("path"):
            lines.append(f"path: {result.get('path')}")
    return "\n".join(lines)


def libgen_summary(data: dict[str, Any]) -> str:
    card = data.get("selected_card") or {}
    decision = data.get("decision") or {}
    links = data.get("links_snapshot") or {}
    lines = [
        f"status: {data.get('status')}",
        f"selected: {card.get('title') or decision.get('selected_title') or '(none)'}",
        f"author: {compact('; '.join(card.get('authors') or [decision.get('selected_author') or '']), 80)}",
        f"file: {card.get('file') or ''}",
        f"links_url: {links.get('url') or ''}",
        f"stop: {data.get('stop_reason') or ''}",
        f"mirror_links: {len(data.get('mirror_links') or [])}",
    ]
    for link in (data.get("mirror_links") or [])[:8]:
        policy = link.get("policy") or {}
        allowed = "allowed" if policy.get("allowed") else "blocked"
        lines.append(f"- {compact(link.get('text') or '(link)', 28)} | {allowed} | {compact(policy.get('stop_reason') or link.get('href'), 90)}")
    return "\n".join(lines)


def run_service_action(action: str, json_output: bool = False) -> int:
    if not VDESKTOP_SCRIPT.exists():
        raise CliError(f"Missing {VDESKTOP_SCRIPT}")
    result = subprocess.run([str(VDESKTOP_SCRIPT), action], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    payload = {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    if json_output:
        print_json(payload)
    else:
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
    return result.returncode


def command_status(args: argparse.Namespace) -> Any:
    return BrowserClient(args.base_url, timeout=args.timeout).get("/api/status", timeout=30)


def command_observe(args: argparse.Namespace) -> Any:
    query = []
    if args.target_id:
        query.append(("target_id", args.target_id))
    query.append(("quality", str(args.quality)))
    return BrowserClient(args.base_url, timeout=args.timeout).get("/api/observe?" + urllib.parse.urlencode(query), timeout=60)


def command_open(args: argparse.Namespace) -> Any:
    endpoint = "/api/guarded-open" if args.guarded else "/api/open"
    return BrowserClient(args.base_url, timeout=args.timeout).post(endpoint, {"url": args.url, "bring_to_front": True}, timeout=60)


def command_goal(args: argparse.Namespace) -> Any:
    return BrowserClient(args.base_url, timeout=args.timeout).post(
        "/api/autonomous-run",
        {
            "goal": args.goal,
            "start_url": args.start_url or "",
            "target_id": args.target_id or "",
            "max_steps": args.max_steps,
            "make_plan": not args.no_plan,
        },
        timeout=args.timeout,
    )


def command_libgen(args: argparse.Namespace) -> Any:
    return BrowserClient(args.base_url, timeout=args.timeout).post(
        "/api/libgen-inspect",
        {"query_or_url": args.query_or_url, "goal": args.goal or ""},
        timeout=args.timeout,
    )


def command_book(args: argparse.Namespace) -> Any:
    return BrowserClient(args.base_url, timeout=args.timeout).post(
        "/api/run-book-task",
        {"query": args.query, "source": "libgen", "goal": args.goal or "", "max_steps": args.max_steps},
        timeout=args.timeout,
    )


def command_download(args: argparse.Namespace) -> Any:
    return BrowserClient(args.base_url, timeout=args.timeout).post(
        "/api/download",
        {"url": args.url, "filename": args.filename or ""},
        timeout=args.timeout,
    )


def command_action(args: argparse.Namespace) -> Any:
    payload: dict[str, Any]
    if args.payload:
        payload = json.loads(args.payload)
    else:
        payload = {}
    return BrowserClient(args.base_url, timeout=args.timeout).post(
        "/api/action",
        {"target_id": args.target_id or "", "action": args.action, "payload": payload},
        timeout=args.timeout,
    )


HELP_TEXT = """Commands:
  /help                         Show this help.
  /status                       Show service/tabs.
  /observe [target_id]          Observe current or selected tab.
  /open <url>                   Open URL.
  /guarded-open <url>           Open URL through safety policy.
  /goal <task>                  Run Autonomous Surf on current tab.
  /start-url <url> <task>       Run Autonomous Surf from URL.
  /libgen <query-or-url>        Select candidate and stop at /links inspection.
  /book <query>                 LibGen search-only candidate selection.
  /download <url>               Guarded public-domain download.
  /service status|start|stop    Manage the vdesktop service.
  /exit                         Exit.

Plain text without a slash is treated as /goal <text>.
"""


def parse_repl_line(line: str) -> tuple[str, list[str]]:
    text = line.strip()
    if not text:
        return "", []
    if not text.startswith("/"):
        return "goal", [text]
    parts = shlex.split(text)
    command = parts[0][1:]
    return command, parts[1:]


def repl(base_url: str, timeout: float, json_output: bool = False) -> int:
    client = BrowserClient(base_url, timeout=timeout)
    print(f"Agentic Browser CLI -> {base_url}")
    print("Use /help for commands. Plain text runs Autonomous Surf.")
    while True:
        try:
            line = input("browser> ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print("\nInterrupted. Use /exit to quit.")
            continue
        command, values = parse_repl_line(line)
        if not command:
            continue
        try:
            if command in {"exit", "quit", "q"}:
                return 0
            if command == "help":
                print(HELP_TEXT.rstrip())
                continue
            if command == "status":
                data = client.get("/api/status", timeout=30)
                print_json(data) if json_output else print(status_summary(data))
            elif command == "observe":
                target_id = values[0] if values else ""
                path = "/api/observe?quality=60" + (f"&target_id={urllib.parse.quote(target_id)}" if target_id else "")
                data = client.get(path, timeout=60)
                print_json(data) if json_output else print(observe_summary(data))
            elif command in {"open", "guarded-open"}:
                if not values:
                    raise CliError(f"/{command} requires a URL")
                endpoint = "/api/guarded-open" if command == "guarded-open" else "/api/open"
                data = client.post(endpoint, {"url": values[0], "bring_to_front": True}, timeout=60)
                print_json(data) if json_output else print(f"opened: {data.get('url')}")
            elif command == "goal":
                goal = " ".join(values).strip()
                if not goal:
                    raise CliError("/goal requires a task")
                data = client.post("/api/autonomous-run", {"goal": goal, "max_steps": 8, "make_plan": True}, timeout=timeout)
                print_json(data) if json_output else print(autonomous_summary(data))
            elif command == "start-url":
                if len(values) < 2:
                    raise CliError("/start-url requires URL and task")
                data = client.post(
                    "/api/autonomous-run",
                    {"start_url": values[0], "goal": " ".join(values[1:]), "max_steps": 8, "make_plan": True},
                    timeout=timeout,
                )
                print_json(data) if json_output else print(autonomous_summary(data))
            elif command == "libgen":
                if not values:
                    raise CliError("/libgen requires query or URL")
                data = client.post("/api/libgen-inspect", {"query_or_url": " ".join(values)}, timeout=timeout)
                print_json(data) if json_output else print(libgen_summary(data))
            elif command == "book":
                if not values:
                    raise CliError("/book requires query")
                data = client.post("/api/run-book-task", {"query": " ".join(values), "source": "libgen", "max_steps": 3}, timeout=timeout)
                print_json(data) if json_output else print_json({"status": data.get("result", {}).get("status"), "query": data.get("query")})
            elif command == "download":
                if not values:
                    raise CliError("/download requires URL")
                data = client.post("/api/download", {"url": values[0]}, timeout=timeout)
                print_json(data)
            elif command == "service":
                if not values:
                    raise CliError("/service requires status, start, or stop")
                run_service_action(values[0], json_output=json_output)
            else:
                raise CliError(f"Unknown command: /{command}")
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentic-browser",
        description="CLI client for the embedded agentic browser.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:
              agentic-browser status
              agentic-browser chat
              agentic-browser goal "Find the title of the current page"
              agentic-browser goal --start-url https://www.gutenberg.org/ebooks/1342 "Download the Plain Text UTF-8 file"
              agentic-browser libgen "https://libgen.pw/book/112502936"
              agentic-browser service start
            """
        ),
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Browser service URL. Default: {DEFAULT_BASE_URL}")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--json", action="store_true", help="Print full JSON response.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status")

    observe = sub.add_parser("observe")
    observe.add_argument("--target-id", default="")
    observe.add_argument("--quality", type=int, default=60)

    open_cmd = sub.add_parser("open")
    open_cmd.add_argument("url")
    open_cmd.add_argument("--guarded", action="store_true")

    goal = sub.add_parser("goal")
    goal.add_argument("goal", nargs="+")
    goal.add_argument("--start-url", default="")
    goal.add_argument("--target-id", default="")
    goal.add_argument("--max-steps", type=int, default=8)
    goal.add_argument("--no-plan", action="store_true")

    libgen = sub.add_parser("libgen")
    libgen.add_argument("query_or_url", nargs="+")
    libgen.add_argument("--goal", default="")

    book = sub.add_parser("book")
    book.add_argument("query", nargs="+")
    book.add_argument("--goal", default="")
    book.add_argument("--max-steps", type=int, default=3)

    download = sub.add_parser("download")
    download.add_argument("url")
    download.add_argument("--filename", default="")

    action = sub.add_parser("action")
    action.add_argument("action")
    action.add_argument("--target-id", default="")
    action.add_argument("--payload", default="", help="JSON action payload.")

    service = sub.add_parser("service")
    service.add_argument("service_action", choices=["start", "stop", "status", "logs"])

    sub.add_parser("chat")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        args.command = "chat"

    try:
        if args.command == "chat":
            return repl(args.base_url, timeout=args.timeout, json_output=args.json)
        if args.command == "service":
            return run_service_action(args.service_action, json_output=args.json)

        if args.command == "status":
            data = command_status(args)
            print_json(data) if args.json else print(status_summary(data))
        elif args.command == "observe":
            data = command_observe(args)
            print_json(data) if args.json else print(observe_summary(data))
        elif args.command == "open":
            data = command_open(args)
            print_json(data) if args.json else print(f"opened: {data.get('url')}")
        elif args.command == "goal":
            args.goal = " ".join(args.goal)
            data = command_goal(args)
            print_json(data) if args.json else print(autonomous_summary(data))
        elif args.command == "libgen":
            args.query_or_url = " ".join(args.query_or_url)
            data = command_libgen(args)
            print_json(data) if args.json else print(libgen_summary(data))
        elif args.command == "book":
            args.query = " ".join(args.query)
            data = command_book(args)
            print_json(data)
        elif args.command == "download":
            data = command_download(args)
            print_json(data)
        elif args.command == "action":
            data = command_action(args)
            print_json(data)
        else:
            parser.error(f"Unsupported command: {args.command}")
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
