#!/usr/bin/env node
import { spawnSync } from "node:child_process";

function commandOk(command, args) {
  const result = spawnSync(command, args, { encoding: "utf8", stdio: "pipe" });
  return !result.error && result.status === 0;
}

const python = process.env.AGINTI_BROWSER_PYTHON || process.env.PYTHON || "python3";
const hasPython = commandOk(python, ["--version"]);
const hasWebsocket = hasPython && commandOk(python, ["-c", "import websocket"]);

if (!hasPython) {
  console.warn("[aginti-browser] Python 3 was not found. Install python3 or set AGINTI_BROWSER_PYTHON before running the CLI.");
} else if (!hasWebsocket) {
  console.warn("[aginti-browser] Python package websocket-client is missing. Install it with: python3 -m pip install websocket-client");
}

