#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const cliPath = path.join(packageRoot, "agentic_browser_cli.py");

function findPython() {
  const candidates = [
    process.env.AGINTI_BROWSER_PYTHON,
    process.env.PYTHON,
    "python3",
    "python",
  ].filter(Boolean);

  for (const candidate of candidates) {
    const result = spawnSync(candidate, ["--version"], { encoding: "utf8" });
    if (!result.error && result.status === 0) return candidate;
  }
  return null;
}

if (!fs.existsSync(cliPath)) {
  console.error(`AgInTi Browser CLI not found: ${cliPath}`);
  process.exit(1);
}

const python = findPython();
if (!python) {
  console.error("AgInTi Browser requires Python 3. Install python3 or set AGINTI_BROWSER_PYTHON.");
  process.exit(1);
}

const existingPythonPath = process.env.PYTHONPATH || "";
const env = {
  ...process.env,
  PYTHONPATH: existingPythonPath ? `${packageRoot}${path.delimiter}${existingPythonPath}` : packageRoot,
};

const result = spawnSync(python, [cliPath, ...process.argv.slice(2)], {
  cwd: process.cwd(),
  env,
  stdio: "inherit",
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(typeof result.status === "number" ? result.status : 1);

