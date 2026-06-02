#!/usr/bin/env python3
"""Process-level browser agent that can browse sites without the GUI."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from embedded_agentic_browser.downloader import download_public_file
from embedded_agentic_browser.open_chrome_driver import OpenChromeDriver
from embedded_agentic_browser.safety import classify_url
from embedded_agentic_browser.server import (
    DEFAULT_BROWSER_PORT,
    DEFAULT_MODEL,
    DEFAULT_PROFILE_DIR,
    DEFAULT_REASONING_EFFORT,
    LOG_DIR,
    policy_dict_for_url,
    wait_for_navigation,
    wait_for_dynamic_results,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TERMINAL_ACTIONS = {"extract", "select", "hold", "stop"}
DEFAULT_DOWNLOAD_DIR = LOG_DIR / "downloads"


class AgentRuntimeError(RuntimeError):
    pass


@dataclass
class AgentRunConfig:
    goal: str
    start_url: str
    target_id: str | None
    max_steps: int
    model: str
    reasoning_effort: str
    browser_port: int
    profile_dir: Path
    log_dir: Path
    download_dir: Path
    make_plan: bool = True


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "plan": {"type": "array", "items": {"type": "string"}},
        "risk_notes": {"type": "string"},
        "done_signal": {"type": "string"},
    },
    "required": ["plan", "risk_notes", "done_signal"],
    "additionalProperties": False,
}


AGENT_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "open_url",
                "click_selector",
                "click_text",
                "type_selector",
                "key",
                "scroll",
                "wait",
                "download_url",
                "extract",
                "select",
                "hold",
                "stop",
            ],
        },
        "url": {"type": "string"},
        "selector": {"type": "string"},
        "text": {"type": "string"},
        "key": {"type": "string"},
        "filename": {"type": "string"},
        "scroll_delta_y": {"type": "integer"},
        "wait_seconds": {"type": "number"},
        "clear_first": {"type": "boolean"},
        "selected_index": {"type": ["integer", "null"]},
        "selected_title": {"type": "string"},
        "selected_author": {"type": "string"},
        "selected_language": {"type": "string"},
        "extracted_answer": {"type": "string"},
        "safety_stop": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": [
        "action",
        "url",
        "selector",
        "text",
        "key",
        "filename",
        "scroll_delta_y",
        "wait_seconds",
        "clear_first",
        "selected_index",
        "selected_title",
        "selected_author",
        "selected_language",
        "extracted_answer",
        "safety_stop",
        "reason",
    ],
    "additionalProperties": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True, help="Task for the browser agent.")
    parser.add_argument("--start-url", default="", help="Optional first URL to open.")
    parser.add_argument("--target-id", default="", help="Existing Chrome target id to control.")
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--browser-port", type=int, default=DEFAULT_BROWSER_PORT)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    parser.add_argument("--log-dir", type=Path, default=LOG_DIR / "agent-runs")
    parser.add_argument("--download-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR)
    parser.add_argument("--no-plan", action="store_true", help="Skip the initial Codex planning pass.")
    parser.add_argument("--json", action="store_true", help="Print final JSON only.")
    return parser.parse_args()


def compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "page": {
            "title": snapshot.get("title"),
            "url": snapshot.get("url"),
            "policy": snapshot.get("policy"),
            "noResults": snapshot.get("noResults"),
            "scroll": snapshot.get("scroll"),
            "viewport": snapshot.get("viewport"),
            "ready_state": snapshot.get("ready_state"),
        },
        "interactive": (snapshot.get("interactive") or [])[:90],
        "cards": (snapshot.get("cards") or [])[:35],
        "links": (snapshot.get("links") or [])[:70],
        "downloadish": (snapshot.get("downloadish") or [])[:35],
        "textSample": (snapshot.get("textSample") or [])[:70],
    }


def build_plan_prompt(goal: str, start_url: str) -> str:
    return f"""
You are planning an autonomous browser run before any browser action is taken.
Make a concise, practical plan for a monitored web browser agent.

Goal:
{goal.strip()}

Start URL:
{start_url.strip() or "(use current controlled browser tab)"}

Rules:
- Keep the plan short and operational.
- Include how the agent should know it is done.
- Call out safety/access-control risks.
- Do not include hidden chain-of-thought. Return only the requested JSON.
""".strip()


def run_codex_agent_plan(goal: str, start_url: str, model: str, reasoning_effort: str) -> dict[str, Any]:
    prompt = build_plan_prompt(goal, start_url)
    with tempfile.TemporaryDirectory(prefix="true-agentic-browser-plan-") as temp_dir:
        schema_path = Path(temp_dir) / "schema.json"
        output_path = Path(temp_dir) / "result.json"
        schema_path.write_text(json.dumps(PLAN_SCHEMA, ensure_ascii=False, indent=2), encoding="utf-8")
        command = [
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
        result = subprocess.run(command, input=prompt, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-1800:]
            raise AgentRuntimeError(f"codex exec plan failed ({result.returncode}): {detail}")
        return json.loads(output_path.read_text(encoding="utf-8"))


def build_agent_prompt(
    goal: str,
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    step_index: int,
    plan: dict[str, Any] | None = None,
) -> str:
    visible_history = [
        {
            "step": item.get("step"),
            "url": item.get("url"),
            "action": (item.get("decision") or {}).get("action"),
            "reason": (item.get("decision") or {}).get("reason"),
            "result": item.get("execution"),
        }
        for item in history[-8:]
    ]
    payload = {
        "step_index": step_index,
        "goal": goal,
        "plan": plan or {},
        "history": visible_history,
        "snapshot": compact_snapshot(snapshot),
    }
    return f"""
You are a true browser-control agent operating a real Chrome tab through CDP.
Choose exactly one next browser action, then stop.

Available actions:
- open_url: navigate the current tab to a safe URL.
- click_selector: click a CSS selector from snapshot.interactive.
- click_text: click a visible clickable element whose label/text contains text.
- type_selector: type text into a selector from snapshot.interactive.
- key: press a keyboard key, usually Enter after typing.
- scroll: scroll the page.
- wait: wait for loading or dynamic UI.
- download_url: download a public-domain/open-source URL, then stop.
- extract: final answer/data extracted; stop.
- select: final book/candidate selection; stop.
- hold: stop for human review.
- stop: stop because task is complete or unsafe.

Rules:
- Use selector actions when the needed input/button is listed in snapshot.interactive.
- For search forms: type_selector into the input, then key Enter or click the Search button.
- Follow the plan, but adapt when the live page state shows a better safe route.
- Do not bypass login, CAPTCHA, paywalls, access control, or rate limits. Use hold.
- Do not open URLs blocked by policy. Shadow-library pages are search/detail inspection only; never open mirrors, downloads, torrents, IPFS, or direct files.
- For public-domain/open sources, you may navigate source/detail pages if policy permits.
- Use download_url only when the user explicitly asks to download and the target URL is a visible public-domain/open-source download link.
- If the task is complete, use extract or select with concise evidence.
- If the page is visibly loading or dynamic results are not ready, use wait.

State:
{json.dumps(payload, ensure_ascii=False, indent=2)}

Return JSON only.
""".strip()


def run_codex_agent_decision(
    goal: str,
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    step_index: int,
    model: str,
    reasoning_effort: str,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = build_agent_prompt(goal, snapshot, history, step_index, plan=plan)
    with tempfile.TemporaryDirectory(prefix="true-agentic-browser-") as temp_dir:
        schema_path = Path(temp_dir) / "schema.json"
        output_path = Path(temp_dir) / "result.json"
        schema_path.write_text(json.dumps(AGENT_DECISION_SCHEMA, ensure_ascii=False, indent=2), encoding="utf-8")
        command = [
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
        result = subprocess.run(command, input=prompt, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-1800:]
            raise AgentRuntimeError(f"codex exec failed ({result.returncode}): {detail}")
        return json.loads(output_path.read_text(encoding="utf-8"))


def observe(driver: OpenChromeDriver, target_id: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            snapshot = wait_for_dynamic_results(driver, target_id)
            snapshot["policy"] = policy_dict_for_url(str(snapshot.get("url") or ""))
            return snapshot
        except Exception as exc:
            last_error = exc
            time.sleep(min(4.0, 0.75 * attempt))
    raise AgentRuntimeError(f"Could not observe target after retries: {last_error}") from last_error


def guard_url(url: str) -> str:
    policy = classify_url(url)
    if not policy.allowed:
        raise AgentRuntimeError(policy.stop_reason)
    return policy.url


def guard_click_action(driver: OpenChromeDriver, target_id: str, decision: dict[str, Any]) -> None:
    snapshot = observe(driver, target_id)
    policy = snapshot.get("policy") or {}
    if not policy.get("is_shadow_library"):
        return

    current_path = urllib.parse.urlparse(str(snapshot.get("url") or "")).path
    action = str(decision.get("action") or "")
    selector = str(decision.get("selector") or "")
    text = str(decision.get("text") or "").strip().lower()

    if current_path.startswith("/links") and text in {"get", "libgen", "annas-archive", "download"}:
        raise AgentRuntimeError("Blocked autonomous click on shadow-library mirror/download link.")

    candidates: list[dict[str, Any]] = []
    if action == "click_selector" and selector:
        candidates.extend(
            element
            for element in snapshot.get("interactive") or []
            if str(element.get("selector") or "") == selector
        )
    elif action == "click_text" and text:
        candidates.extend(
            link
            for link in snapshot.get("links") or []
            if text in str(link.get("text") or "").strip().lower()
        )

    for candidate in candidates:
        href = str(candidate.get("href") or "")
        if not href.startswith(("http://", "https://")):
            continue
        link_policy = classify_url(href)
        if not link_policy.allowed:
            raise AgentRuntimeError(link_policy.stop_reason)


def execute_agent_action(driver: OpenChromeDriver, target_id: str, decision: dict[str, Any], download_dir: Path = DEFAULT_DOWNLOAD_DIR) -> dict[str, Any]:
    action = str(decision.get("action") or "")
    if action in TERMINAL_ACTIONS:
        return {"terminal": True, "status": action}
    if action == "open_url":
        url = guard_url(str(decision.get("url") or ""))
        result = driver.action(target_id, "navigate", {"url": url})
    elif action == "click_selector":
        guard_click_action(driver, target_id, decision)
        result = driver.action(target_id, "click_selector", {"selector": str(decision.get("selector") or "")})
    elif action == "click_text":
        guard_click_action(driver, target_id, decision)
        result = driver.action(target_id, "click_text", {"text": str(decision.get("text") or "")})
    elif action == "type_selector":
        result = driver.action(
            target_id,
            "type_selector",
            {
                "selector": str(decision.get("selector") or ""),
                "text": str(decision.get("text") or ""),
                "clear_first": bool(decision.get("clear_first", True)),
            },
        )
    elif action == "key":
        result = driver.action(target_id, "key", {"key": str(decision.get("key") or "Enter")})
    elif action == "scroll":
        result = driver.action(target_id, "scroll", {"delta_y": int(decision.get("scroll_delta_y") or 700)})
    elif action == "wait":
        result = driver.action(target_id, "wait", {"seconds": max(0.1, min(10.0, float(decision.get("wait_seconds") or 1.0)))})
    elif action == "download_url":
        download = download_public_file(
            str(decision.get("url") or ""),
            download_dir,
            requested_filename=str(decision.get("filename") or ""),
        )
        return {"terminal": True, "status": "download", "result": download}
    else:
        raise AgentRuntimeError(f"Unsupported agent action: {action}")
    return {"terminal": False, "status": "executed", "result": result}


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_agent(config: AgentRunConfig) -> dict[str, Any]:
    if not config.goal.strip():
        raise AgentRuntimeError("Goal is required")
    driver = OpenChromeDriver(config.browser_port, config.profile_dir)
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    log_path = config.log_dir / f"{run_id}.jsonl"
    plan: dict[str, Any] = {"plan": [], "risk_notes": "", "done_signal": ""}

    if config.make_plan:
        try:
            plan = run_codex_agent_plan(config.goal, config.start_url, config.model, config.reasoning_effort)
        except Exception as exc:
            plan = {
                "plan": ["Continue step by step from the current browser state."],
                "risk_notes": f"Plan generation failed: {exc}",
                "done_signal": "Stop when the goal is complete, unsafe, or blocked.",
            }
        append_jsonl(
            log_path,
            {
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "run_id": run_id,
                "event": "plan",
                "plan": plan,
            },
        )

    if config.start_url:
        start_url = guard_url(config.start_url)
        target = driver.new_tab(start_url)
        target_id = target.id
        wait_for_navigation(driver, target_id, start_url)
    else:
        target = driver.target(config.target_id)
        target_id = target.id

    history: list[dict[str, Any]] = []
    final_status = "max_steps"
    final_decision: dict[str, Any] | None = None
    started = time.time()

    for step_index in range(1, max(1, config.max_steps) + 1):
        try:
            snapshot = observe(driver, target_id)
            decision = run_codex_agent_decision(
                config.goal,
                snapshot,
                history,
                step_index,
                config.model,
                config.reasoning_effort,
                plan=plan,
            )
        except Exception as exc:
            record = {
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "run_id": run_id,
                "step": step_index,
                "url": "",
                "title": "",
                "decision": None,
                "execution": {"terminal": True, "status": "error", "error": str(exc)},
            }
            append_jsonl(log_path, record)
            history.append(record)
            final_status = "error"
            break
        try:
            execution = execute_agent_action(driver, target_id, decision, config.download_dir)
        except Exception as exc:
            execution = {"terminal": True, "status": "error", "error": str(exc)}
        record = {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "run_id": run_id,
            "step": step_index,
            "url": snapshot.get("url"),
            "title": snapshot.get("title"),
            "decision": decision,
            "execution": execution,
        }
        append_jsonl(log_path, record)
        history.append(record)
        final_decision = decision
        if execution.get("terminal") or decision.get("safety_stop"):
            final_status = str(execution.get("status") or decision.get("action") or "stop")
            break
        time.sleep(0.8)

    summary = {
        "ok": final_status not in {"error"},
        "run_id": run_id,
        "status": final_status,
        "target_id": target_id,
        "steps": len(history),
        "duration_seconds": round(time.time() - started, 2),
        "log_path": str(log_path),
        "plan": plan,
        "step_records": history,
        "final_decision": final_decision,
    }
    append_jsonl(log_path, {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "run_id": run_id, "summary": summary})
    return summary


def main() -> int:
    args = parse_args()
    config = AgentRunConfig(
        goal=args.goal,
        start_url=args.start_url,
        target_id=args.target_id or None,
        max_steps=args.max_steps,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        browser_port=args.browser_port,
        profile_dir=args.profile_dir,
        log_dir=args.log_dir,
        download_dir=args.download_dir,
        make_plan=not args.no_plan,
    )
    summary = run_agent(config)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Agent run {summary['run_id']} finished: {summary['status']} in {summary['steps']} steps")
        print(f"Target: {summary['target_id']}")
        print(f"Log: {summary['log_path']}")
        if summary.get("final_decision"):
            print(json.dumps(summary["final_decision"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
