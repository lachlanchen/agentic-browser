#!/usr/bin/env python3
"""Standalone app-mode launcher for the embedded agentic browser."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

from embedded_agentic_browser.open_chrome_driver import find_chrome_binary
from embedded_agentic_browser.server import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    LOG_DIR,
    REPO_ROOT,
)


DEFAULT_APP_PORT = 8792
DEFAULT_CONTROLLED_BROWSER_PORT = 9444
DEFAULT_CONTROLLED_PROFILE = Path.home() / ".cache" / "standalone-agentic-browser-controlled"
DEFAULT_SHELL_PROFILE = Path.home() / ".cache" / "standalone-agentic-browser-shell"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_APP_PORT, help="Local GUI/backend port.")
    parser.add_argument("--browser-port", type=int, default=DEFAULT_CONTROLLED_BROWSER_PORT, help="CDP port for the controlled browsing engine.")
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_CONTROLLED_PROFILE, help="Profile used by the controlled browsing engine.")
    parser.add_argument("--shell-profile-dir", type=Path, default=DEFAULT_SHELL_PROFILE, help="Profile used by the app-mode shell window.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    parser.add_argument("--reuse-server", action="store_true", help="Do not start a backend; just open an app window for the existing URL.")
    parser.add_argument("--no-open", action="store_true", help="Start/reuse backend without opening the app-mode shell window.")
    return parser.parse_args()


def app_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def status_url(host: str, port: int) -> str:
    return f"{app_url(host, port)}/api/status"


def is_backend_ready(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(status_url(host, port), timeout=2) as response:
            json.load(response)
        return True
    except Exception:
        return False


def wait_for_backend(host: str, port: int, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_backend_ready(host, port):
            return
        time.sleep(0.5)
    raise RuntimeError(f"Backend did not become ready: {status_url(host, port)}")


def build_server_command(args: argparse.Namespace) -> list[str]:
    return [
        "python3",
        "-m",
        "embedded_agentic_browser.server",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--browser-port",
        str(args.browser_port),
        "--profile-dir",
        str(args.profile_dir),
        "--model",
        args.model,
        "--reasoning-effort",
        args.reasoning_effort,
    ]


def build_app_chrome_command(url: str, shell_profile_dir: Path) -> list[str]:
    return [
        find_chrome_binary(),
        f"--app={url}",
        f"--user-data-dir={shell_profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--class=AgenticBrowser",
        "--window-size=1480,960",
    ]


def start_backend(args: argparse.Namespace) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "standalone-app-server.log"
    handle = log_path.open("ab")
    return subprocess.Popen(
        build_server_command(args),
        cwd=str(REPO_ROOT),
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def launch_app_window(url: str, shell_profile_dir: Path) -> subprocess.Popen:
    shell_profile_dir.mkdir(parents=True, exist_ok=True)
    command = build_app_chrome_command(url, shell_profile_dir)
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def profile_chrome_pids(pgrep_output: str, current_pid: int) -> list[int]:
    pids: list[int] = []
    for line in pgrep_output.splitlines():
        parts = line.strip().split(maxsplit=1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid != current_pid:
            pids.append(pid)
    return pids


def stop_controlled_browser(profile_dir: Path) -> None:
    result = subprocess.run(
        ["pgrep", "-af", str(profile_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    for pid in profile_chrome_pids(result.stdout, os.getpid()):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue


def main() -> int:
    args = parse_args()
    server_process: subprocess.Popen | None = None
    url = app_url(args.host, args.port)

    if not args.reuse_server:
        server_process = start_backend(args)
    wait_for_backend(args.host, args.port)

    app_process = None
    if not args.no_open:
        app_process = launch_app_window(url, args.shell_profile_dir)

    print(f"Standalone Agentic Browser: {url}")
    print(f"Controlled browser CDP: http://127.0.0.1:{args.browser_port}")
    print(f"Controlled profile: {args.profile_dir}")
    print(f"Shell profile: {args.shell_profile_dir}")

    if args.reuse_server:
        return 0

    assert server_process is not None
    try:
        while server_process.poll() is None:
            time.sleep(1.0)
    except KeyboardInterrupt:
        try:
            server_process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
        if app_process and app_process.poll() is None:
            try:
                app_process.terminate()
            except ProcessLookupError:
                pass
        stop_controlled_browser(args.profile_dir)
    return server_process.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
