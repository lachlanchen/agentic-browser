#!/usr/bin/env node
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";

function parseDotenv(text = "") {
  const values = {};
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const match = trimmed.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    values[match[1]] = value;
  }
  return values;
}

function registryHost(registry = "") {
  try {
    return new URL(registry).host || "registry.npmjs.org";
  } catch {
    return "registry.npmjs.org";
  }
}

async function readEnvFile() {
  const candidates = [
    process.env.AGINTI_BROWSER_NPM_ENV,
    path.join(repoRoot, ".env"),
  ].filter(Boolean);

  const failures = [];
  for (const candidate of candidates) {
    try {
      const text = await fs.readFile(candidate, "utf8");
      return { path: candidate, values: parseDotenv(text) };
    } catch (error) {
      failures.push(candidate);
    }
  }
  throw new Error(`No npm env file found. Tried: ${failures.join(", ")}`);
}

async function runNpm(args, env) {
  return new Promise((resolve) => {
    const child = spawn(npmCommand, args, {
      cwd: repoRoot,
      env,
      stdio: ["ignore", "inherit", "inherit"],
    });
    child.on("close", (code) => resolve(Number(code) || 0));
    child.on("error", (error) => {
      console.error(error instanceof Error ? error.message : String(error));
      resolve(1);
    });
  });
}

async function main() {
  const npmArgs = process.argv.slice(2).length ? process.argv.slice(2) : ["publish", "--access", "public"];
  const loaded = await readEnvFile();
  const token = loaded.values.NPM_TOKEN || loaded.values.NODE_AUTH_TOKEN;
  const registry = loaded.values.NPM_CONFIG_REGISTRY || "https://registry.npmjs.org/";
  if (!token) {
    console.error(`No NPM_TOKEN or NODE_AUTH_TOKEN found in ${loaded.path}`);
    process.exit(1);
  }

  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "aginti-browser-npmrc-"));
  const npmrcPath = path.join(tempDir, ".npmrc");
  try {
    const host = registryHost(registry);
    await fs.writeFile(
      npmrcPath,
      [
        `registry=${registry}`,
        `//${host}/:_authToken=${token}`,
        "always-auth=true",
        "",
      ].join("\n"),
      { mode: 0o600 }
    );
    const code = await runNpm(npmArgs, {
      ...process.env,
      NPM_CONFIG_USERCONFIG: npmrcPath,
      npm_config_userconfig: npmrcPath,
      NODE_AUTH_TOKEN: token,
      NPM_TOKEN: token,
      NPM_CONFIG_REGISTRY: registry,
    });
    process.exit(code);
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true }).catch(() => {});
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});

