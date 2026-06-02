"""Codex wrapper with an AgInTi-style one-step steering contract."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


class CodexWrapperError(RuntimeError):
    pass


DECISION_SCHEMA = {
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


def build_prompt(goal: str, snapshot: dict[str, Any], step_index: int) -> str:
    compact = {
        "step_index": step_index,
        "page": {
            "title": snapshot.get("title"),
            "url": snapshot.get("url"),
            "policy": snapshot.get("policy"),
            "noResults": snapshot.get("noResults"),
            "scroll": snapshot.get("scroll"),
        },
        "cards": (snapshot.get("cards") or [])[:35],
        "links": (snapshot.get("links") or [])[:80],
        "downloadish": (snapshot.get("downloadish") or [])[:40],
        "textSample": (snapshot.get("textSample") or [])[:45],
    }
    return f"""
You are the AgInTi-style browser steering model. Make exactly one safe next-step
decision for a monitored browser, then stop.

Goal:
{goal.strip() or "Search for a book, choose the best candidate, and stop with a decision."}

Actions:
- select: final candidate found; stop.
- open_url: open a safe source/search/detail URL.
- scroll: inspect more of the current page.
- wait: wait for dynamic content.
- hold: stop for human review because evidence is insufficient.
- stop: task complete or unsafe.

Rules:
- Search results are evidence; output a decision.
- Prefer exact title, exact author, correct language, and complete sets.
- Do not recommend shadow-library mirror/download/direct-file pages.
- Public-domain/open sources may proceed to source/detail/final pre-download pages.
- For Figma/BioRender/design tools, assume the user monitors login/session in
  the controlled browser; do not bypass access control.

Snapshot:
{json.dumps(compact, ensure_ascii=False, indent=2)}

Return JSON only.
""".strip()


def run_codex_decision(
    goal: str,
    snapshot: dict[str, Any],
    step_index: int,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    prompt = build_prompt(goal, snapshot, step_index)
    with tempfile.TemporaryDirectory(prefix="embedded-agentic-codex-") as temp_dir:
        schema_path = Path(temp_dir) / "schema.json"
        output_path = Path(temp_dir) / "result.json"
        schema_path.write_text(json.dumps(DECISION_SCHEMA, ensure_ascii=False, indent=2), encoding="utf-8")
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
            detail = (result.stderr or result.stdout or "").strip()[-1800:]
            raise CodexWrapperError(f"codex exec failed ({result.returncode}): {detail}")
        return json.loads(output_path.read_text(encoding="utf-8"))
