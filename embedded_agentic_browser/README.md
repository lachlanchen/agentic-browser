# AgInTi Browser

Alternative agentic browser implementation in a folder parallel to the previous `agentic_browser_site` webapp.

Powered by AgInTi Flow: https://flow.lazying.art

## What It Does

- Runs a local GUI at `http://127.0.0.1:8791`.
- Launches or attaches to Chrome/Chromium through Chrome DevTools Protocol on port `9333`.
- Shows an embedded screenshot viewport that can be clicked, scrolled, typed into, reloaded, and navigated.
- Uses `/api/observe` to return the screenshot and DOM elements/selectors together, so GUI controls and agent controls share the same page state.
- Uses `codex exec` as a one-step AgInTi-style steering model with JSON output.
- Runs Autonomous Surf from the GUI or `/api/autonomous-run`: Codex first makes
  a concise plan, then each browser step calls the process-level Codex wrapper
  for the next action.
- Runs a high-level book task from a query: open search, wait for dynamic results, then autopilot to `select` or `hold`.
- Runs LibGen Inspect to Links from the GUI or `/api/libgen-inspect`: choose a
  visible candidate, click the in-page file metadata route, open `/links/...`,
  classify mirror links, and stop before mirror/download navigation.
- Keeps a safety policy between agent decisions and browser navigation.
- Logs actions to `library/embedded-agentic-browser/actions.jsonl`.

## Run

```bash
./run-embedded-agentic-browser.sh
```

Run as a standalone browser-like app window with its own shell profile and its
own controlled browsing engine:

```bash
./run-agentic-browser-app.sh
```

Defaults:

- App window/backend: `http://127.0.0.1:8792`
- Controlled browser CDP: `http://127.0.0.1:9444`
- Controlled profile: `~/.cache/standalone-agentic-browser-controlled`
- Shell profile: `~/.cache/standalone-agentic-browser-shell`

This is not a Chromium fork or replacement binary. It is a dedicated app-mode
Chrome/Chromium shell plus a separate controlled Chrome/Chromium instance with
agent actions, observations, and safety policy.

Run the process-level browser agent without using the GUI:

```bash
./run-true-agentic-browser.sh \
  --goal "Open the page, search for Pride and Prejudice, and select the best visible candidate." \
  --start-url "https://libgen.pw/" \
  --max-steps 8
```

The agent observes the real Chrome tab, asks `codex exec` for one next action, then executes browser actions such as `open_url`, `click_selector`, `click_text`, `type_selector`, `key`, `scroll`, `wait`, and `download_url`. It writes per-step logs under `library/embedded-agentic-browser/agent-runs/`.

The GUI's Autonomous Surf control uses the same runtime through
`/api/autonomous-run`, so manual monitoring and full autonomous runs share the
same Chrome profile, safety checks, downloads folder, and run logs.

If the task explicitly asks to download from an allowed public-domain/open
source, the agent can use `download_url`. Downloads are saved under
`library/embedded-agentic-browser/downloads/`.

Example:

```bash
./run-true-agentic-browser.sh \
  --goal "On this Project Gutenberg book page, download the Plain Text UTF-8 file for Pride and Prejudice by Jane Austen." \
  --start-url "https://www.gutenberg.org/ebooks/1342" \
  --max-steps 5 \
  --json
```

To use an existing CDP browser, start Chrome/Chromium yourself and pass its port:

```bash
EMBEDDED_AGENTIC_BROWSER_PORT=9222 ./run-embedded-agentic-browser.sh
```

To run in tmux:

```bash
tmux new-session -d -s embedded-agentic-browser './run-embedded-agentic-browser.sh'
```

## Safety Model

The tool allows normal browsing, public-domain sources, and design tools such as Figma/BioRender under the user's existing browser session. It blocks agent-driven navigation into shadow-library mirror/download/direct-file URLs and blocks non-public direct binary URLs. LibGen-style pages are treated as inspection/search/detail/link-list pages only, so a LibGen book task finishes at candidate selection, `/links/...` inspection, or human-review hold. File downloads are enabled only for public-domain/open hosts.

This does not bypass login, access control, paywalls, or site restrictions. It gives the local user a monitored browser and a Codex decision wrapper.
