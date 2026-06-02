# Agentic Browser Guide

This repo now has a real Chrome/Chromium-backed agentic browser tool. It is not
a browser engine from scratch. It uses open Chrome through Chrome DevTools
Protocol (CDP), observes screenshots and DOM state, asks `codex exec` for
bounded JSON decisions, executes browser actions, and logs each run.

## Current Main Tool

Use the newer embedded browser as the main version:

```bash
./run-embedded-agentic-browser.sh
```

Defaults:

- GUI/API: `http://127.0.0.1:8791`
- Controlled Chrome CDP: `http://127.0.0.1:9333`
- Model: `gpt-5.4-mini`
- Reasoning: `low`
- Action log: `library/embedded-agentic-browser/actions.jsonl`
- Agent run logs: `library/embedded-agentic-browser/agent-runs/`
- Public-domain downloads: `library/embedded-agentic-browser/downloads/`

The older GUI still exists:

```bash
./run-agentic-browser-gui.sh
```

Defaults:

- GUI/API: `http://127.0.0.1:8789`
- Controlled Chrome CDP: `http://127.0.0.1:9223`

The older `8789` UI style was ported into the newer `8791` implementation. The
newer `8791` backend is the development base.

Where things open:

- The webapp tool is served by `embedded_agentic_browser/server.py` from
  `embedded_agentic_browser/static/`.
- The main webapp URL is `http://127.0.0.1:8791`.
- The visible controlled Chrome browser is launched by
  `embedded_agentic_browser/open_chrome_driver.py`.
- The main controlled Chrome CDP URL is `http://127.0.0.1:9333`.
- The main controlled Chrome profile is
  `~/.cache/embedded-agentic-browser-chrome`.
- If a Chrome window appears on your real desktop, it is the controlled browser,
  not the webapp server.

## Main Files

- `embedded_agentic_browser/server.py`
  Local HTTP GUI/API server. Owns endpoints, task flows, policy checks, and
  links together the driver, Codex wrapper, downloader, and true agent runtime.

- `embedded_agentic_browser/open_chrome_driver.py`
  CDP driver. Launches/attaches Chrome, lists tabs, captures screenshots,
  collects DOM snapshots, exposes cards/links/interactive selectors, and
  executes click/type/key/scroll/navigation actions.

- `embedded_agentic_browser/agent.py`
  Process-level autonomous browser agent. It can run without the GUI. It plans
  with `codex exec`, observes the live page, asks for one JSON action per step,
  executes it, and logs every step.

- `embedded_agentic_browser/codex_aginti_wrapper.py`
  Smaller one-step Codex decision wrapper used by bounded GUI autopilot and
  candidate selection flows.

- `embedded_agentic_browser/safety.py`
  Navigation policy. Allows normal browsing, public-domain/open sources, design
  tools, and shadow-library inspection pages. Blocks shadow-library mirror,
  resolver, download, torrent, IPFS, and direct-file navigation.

- `embedded_agentic_browser/downloader.py`
  Guarded downloader. Downloads only from public-domain/open hosts. Blocks
  shadow-library and non-public direct binary downloads.

- `embedded_agentic_browser/static/`
  The `8791` GUI: warm paper visual style, embedded screenshot viewport, DOM
  observation, manual controls, Codex step, bounded autopilot, Autonomous Surf,
  and LibGen Inspect to Links.

- `embedded_agentic_browser/tests/`
  Unit tests for safety policy, server routes, downloader, standalone app, and
  agent execution guards.

## Root Scripts

```bash
./run-embedded-agentic-browser.sh
```

Starts the main `8791` GUI/API.

```bash
./run-agentic-browser-app.sh
```

Starts a standalone app-mode Chrome shell around the GUI, with a separate
controlled Chrome instance.

```bash
./run-true-agentic-browser.sh --goal "..." --start-url "..." --max-steps 8
```

Runs the process-level autonomous browser agent without opening the GUI.

```bash
./run-agentic-browser-gui.sh
```

Starts the older `8789` prototype GUI.

```bash
./run-agentic-browser-vdesktop.sh start
```

Starts an isolated virtual-display instance so the controlled Chrome does not
open as a top-level window on your current desktop. Default isolated ports are:

- GUI/API: `http://127.0.0.1:8794`
- Controlled Chrome CDP: `http://127.0.0.1:9344`
- Profile: `~/.cache/agentic-browser-vdesktop-chrome`

```bash
./agentic-browser chat
```

Starts the CLI chat/REPL client. It talks to the same browser service as the
webapp. By default it uses `http://127.0.0.1:8794`, the isolated virtual desktop
instance.

## GUI Controls

Open:

- `Open`: opens any normalized URL in the controlled browser.
- `Guarded Open`: opens only if the safety policy allows the URL.
- Quick buttons: open common sources such as LibGen search, Wikisource, Aozora,
  ctext, Figma, and BioRender.

Embedded Viewport:

- Shows a screenshot of the selected Chrome tab.
- Click inside the screenshot to dispatch a browser click.
- Supports Capture, Back, Forward, Reload, Up, Down, Type, and Enter.

Observation:

- Shows policy state.
- Shows interactive elements with CSS selectors.
- Shows structured book cards.
- Shows download-looking links.
- Shows visible text sample.

Codex Step:

- Calls `/api/agent-step`.
- Uses `codex exec` for one JSON decision from the current snapshot.
- Does not execute the decision until the user clicks `Execute Last Decision`.

Bounded Autopilot:

- Calls `/api/autopilot`.
- Uses the smaller one-step wrapper.
- Supports `open_url`, `scroll`, `wait`, `select`, `hold`, `stop`.

Autonomous Surf:

- Calls `/api/autonomous-run`.
- Uses `embedded_agentic_browser/agent.py`.
- First asks Codex for a concise plan.
- Then each step asks Codex for one browser action.
- Supports `open_url`, `click_selector`, `click_text`, `type_selector`, `key`,
  `scroll`, `wait`, `download_url`, `extract`, `select`, `hold`, `stop`.
- Downloads only through the guarded public-domain downloader.

LibGen Inspect to Links:

- Calls `/api/libgen-inspect`.
- Accepts either a search URL, a book URL, or a plain query.
- Opens the search or detail inspection page.
- Uses Codex to select the best visible candidate from result cards.
- Clicks the visible file metadata route, such as `epub, 0.06 MB`, to reach
  `/links/...`.
- Supports direct `/book/<id>` fallback to `/links/<id>`.
- Classifies visible mirror links and stops before mirror/download navigation.

## CLI

The CLI entrypoint is:

```bash
./agentic-browser
```

Default service:

- `AGENTIC_BROWSER_URL` or `http://127.0.0.1:8794`

One-shot commands:

```bash
./agentic-browser status
./agentic-browser observe
./agentic-browser open --guarded https://example.com
./agentic-browser goal --start-url https://example.com --max-steps 4 "Extract the visible page title and stop."
./agentic-browser libgen "https://libgen.pw/book/112502936"
./agentic-browser download "https://www.gutenberg.org/ebooks/1342.txt.utf-8"
./agentic-browser service status
./agentic-browser service start
./agentic-browser service stop
```

Interactive REPL:

```bash
./agentic-browser chat
```

REPL commands:

```text
/help
/status
/observe [target_id]
/open <url>
/guarded-open <url>
/goal <task>
/start-url <url> <task>
/libgen <query-or-url>
/book <query>
/download <url>
/service status|start|stop
/exit
```

Plain text without a slash is treated as `/goal <text>`, so CLI chat can be used
like a lightweight browser agent prompt.

Machine-readable output:

```bash
./agentic-browser --json status
./agentic-browser --json goal --start-url https://example.com "Extract the visible page title and stop."
```

Different service URL:

```bash
AGENTIC_BROWSER_URL=http://127.0.0.1:8791 ./agentic-browser status
./agentic-browser --base-url http://127.0.0.1:8791 status
```

## API Endpoints

GET:

- `/api/status`
  Returns Chrome port, tab list, model, reasoning, and action log path.

- `/api/snapshot?target_id=...`
  Returns DOM snapshot only.

- `/api/viewport?target_id=...&quality=74`
  Returns screenshot only.

- `/api/observe?target_id=...&quality=74`
  Returns screenshot and DOM snapshot together.

POST:

- `/api/open`
  Open a URL without guard.

- `/api/guarded-open`
  Open a URL after policy check.

- `/api/action`
  Execute browser action: click, click selector, click text, type, type selector,
  key, scroll, reload, back, forward, navigate, wait.

- `/api/agent-step`
  Ask Codex for one decision from current page.

- `/api/autopilot`
  Run bounded one-step-wrapper autopilot.

- `/api/autonomous-run`
  Run the true autonomous browser agent with plan and per-step decisions.

- `/api/run-book-task`
  Open LibGen search, wait for dynamic results, select/hold candidate.

- `/api/libgen-inspect`
  Search/select/open LibGen `/links/...` inspection page and stop.

- `/api/download`
  Download a file only if the guarded public-domain downloader allows it.

## Safety Model

Allowed:

- Normal browser pages.
- Public-domain/open hosts such as Gutenberg, Wikisource, ctext, Aozora,
  Standard Ebooks, Archive.org.
- Design tools such as Figma and BioRender, assuming the user controls login.
- LibGen-style search/detail/link-list inspection:
  `/`, `/search...`, `/book/...`, `/links/...`.

Blocked:

- Shadow-library resolver URLs such as `libgen.net/?l=...`.
- Shadow-library mirror/download/direct-file URLs.
- `download`, `get`, `mirror`, `ipfs`, `torrent` paths on shadow-library hosts.
- Direct binary URLs on non-public-domain hosts.
- Non-search/detail/link paths on shadow-library hosts.

Important behavior:

- The tool can open LibGen `/links/...` pages for inspection.
- The tool will not click `Libgen`, `Annas-archive`, `Get`, or equivalent mirror
  download links automatically.
- The tool will not download from LibGen or similar shadow libraries.
- Public-domain downloads are supported and tested.

## Validated Flows

Public-domain autonomous download:

```bash
curl -sS http://127.0.0.1:8791/api/autonomous-run \
  -H 'Content-Type: application/json' \
  -d '{
    "start_url": "https://www.gutenberg.org/ebooks/1342",
    "goal": "On this Project Gutenberg public-domain book page, download the Plain Text UTF-8 file for Pride and Prejudice by Jane Austen. Use a visible public-domain download link and stop after the file is saved.",
    "max_steps": 6,
    "make_plan": true
  }'
```

Observed result:

- Status: `download`
- File: `library/embedded-agentic-browser/downloads/pg1342-3.txt`
- Size: `772386` bytes
- Run log: `library/embedded-agentic-browser/agent-runs/20260602-122701-2afd54.jsonl`

LibGen search-to-links inspection:

```bash
curl -sS http://127.0.0.1:8791/api/libgen-inspect \
  -H 'Content-Type: application/json' \
  -d '{
    "query_or_url": "https://libgen.pw/search?query=%E3%83%9E%E3%83%BC%E3%82%AC%E3%83%AC%E3%83%83%E3%83%88+%E3%83%9F%E3%83%83%E3%83%81%E3%82%A7%E3%83%AB&collection=libgen",
    "goal": "Select the best top-ranked Japanese Margaret Mitchell candidate and stop at links inspection page."
  }'
```

Observed result:

- Selected: `風と共に去りぬ 第2巻（新潮文庫）`
- File metadata: `epub, 0.06 MB`
- Links page: `https://libgen.pw/links/112502936`
- Mirror links classified as blocked.

CLI validation against `http://127.0.0.1:8794`:

```bash
./agentic-browser status
./agentic-browser observe --quality 35
./agentic-browser open --guarded https://example.com
./agentic-browser goal --start-url https://example.com --max-steps 4 "Extract the visible page title and stop."
./agentic-browser libgen "https://libgen.pw/book/112502936"
printf '/status\n/observe\n/exit\n' | ./agentic-browser chat
```

Observed result:

- `status` reported CDP `9344`, model `gpt-5.4-mini / low`.
- `open --guarded https://example.com` opened a tab in the headless controlled
  browser.
- `observe` reported `Example Domain`, regular allowed policy, and DOM state.
- Autonomous CLI goal completed with status `extract`, run
  `20260602-130503-a3e6e7`.
- LibGen CLI inspection reached `https://libgen.pw/links/112502936` and blocked
  mirror/resolver links.
- Piped CLI chat executed `/status`, `/observe`, and `/exit`.

Tmux CLI validation:

```bash
tmux new-session -d -s agentic-browser-cli-tdv bash
tmux send-keys -t agentic-browser-cli-tdv 'cd /home/lachlan/ProjectsLFS/Books && ./agentic-browser chat' Enter
tmux send-keys -t agentic-browser-cli-tdv '/status' Enter
tmux send-keys -t agentic-browser-cli-tdv '/observe' Enter
tmux send-keys -t agentic-browser-cli-tdv '/exit' Enter
tmux capture-pane -p -t agentic-browser-cli-tdv -S -120
```

Observed result:

- CLI stayed interactive in tmux.
- `/status` listed live tabs from CDP `9344`.
- `/observe` reported the active `https://libgen.pw/links/112502936` tab.
- `/exit` returned to a clean shell prompt.

CLI public-domain download validation:

```bash
./agentic-browser goal \
  --start-url https://www.gutenberg.org/ebooks/1342 \
  --max-steps 5 \
  "On this Project Gutenberg public-domain book page, download the Plain Text UTF-8 file for Pride and Prejudice by Jane Austen. Use a visible public-domain download link and stop after the file is saved."
```

Observed result:

- Status: `download`
- Run: `20260602-130618-786ec9`
- File: `library/embedded-agentic-browser/downloads/pg1342-4.txt`
- Size: `772386` bytes

LibGen direct book-to-links inspection:

```bash
curl -sS http://127.0.0.1:8791/api/libgen-inspect \
  -H 'Content-Type: application/json' \
  -d '{
    "query_or_url": "https://libgen.pw/book/112502936",
    "goal": "Reach only links inspection page and stop before mirror/download pages."
  }'
```

Observed result:

- Start: `https://libgen.pw/book/112502936`
- Links page: `https://libgen.pw/links/112502936`
- Page text included `Get`, `Libgen`, `Annas-archive`.
- Mirror links classified as blocked.

## Testing

Run all tests:

```bash
python3 -m unittest discover -s embedded_agentic_browser/tests
```

Current passing count:

```text
42 tests OK
```

Run compile checks:

```bash
python3 -m py_compile \
  embedded_agentic_browser/agent.py \
  embedded_agentic_browser/server.py \
  embedded_agentic_browser/open_chrome_driver.py \
  embedded_agentic_browser/safety.py
```

## Tmux

Start main service:

```bash
tmux new-session -d -s embedded-agentic-browser './run-embedded-agentic-browser.sh'
```

Restart main service:

```bash
tmux kill-session -t embedded-agentic-browser || true
tmux new-session -d -s embedded-agentic-browser './run-embedded-agentic-browser.sh'
```

Check logs:

```bash
tmux capture-pane -p -t embedded-agentic-browser -S -80
```

## Virtual Desktop Deployment

Problem:

- A normal controlled Chrome launch opens a real top-level Chrome window.
- `Page.bringToFront` can raise that Chrome window and interrupt your active
  desktop work.

Solution:

- Use `run-agentic-browser-vdesktop.sh` to start the tool in an isolated display
  and separate tmux session.
- The agent/browser work then happens away from the main `8791` instance.
- You control it from the webapp screenshot/DOM UI at `http://127.0.0.1:8794`.

Start:

```bash
./run-agentic-browser-vdesktop.sh start
```

Stop:

```bash
./run-agentic-browser-vdesktop.sh stop
```

Status:

```bash
./run-agentic-browser-vdesktop.sh status
```

Logs:

```bash
./run-agentic-browser-vdesktop.sh logs
```

Mode selection:

```bash
AGENTIC_VDESKTOP_MODE=auto ./run-agentic-browser-vdesktop.sh start
AGENTIC_VDESKTOP_MODE=xvfb ./run-agentic-browser-vdesktop.sh start
AGENTIC_VDESKTOP_MODE=xephyr ./run-agentic-browser-vdesktop.sh start
AGENTIC_VDESKTOP_MODE=headless ./run-agentic-browser-vdesktop.sh start
```

Mode behavior:

- `xvfb`: best isolated desktop mode, fully off-screen. Requires `Xvfb`.
- `xephyr`: nested X desktop in one container window. Requires `Xephyr`.
- `headless`: no X desktop; Chrome runs with `--headless=new`. Use the webapp
  screenshot/DOM UI for access.
- `auto`: chooses `xvfb` if available, then `xephyr`, then `headless`.
- Default mode is `headless` to avoid stealing focus from the real desktop.

Current machine status observed during setup:

- `Xephyr` is installed.
- `google-chrome` is installed.
- `Xvfb`, `x11vnc`, `websockify`, `noVNC`, `openbox`, and `fluxbox` were not
  installed.
- This Xephyr build accepts `AGENTIC_VDESKTOP_XEPHYR_DEPTH=16/16`; 24/32-bit
  screen depths failed during validation.

Recommended modes:

- If you want zero visible windows: use `AGENTIC_VDESKTOP_MODE=headless`.
- If you want a movable contained desktop window: use
  `AGENTIC_VDESKTOP_MODE=xephyr`.
- If you later install `Xvfb`: use `AGENTIC_VDESKTOP_MODE=xvfb`.

Custom ports/profile:

```bash
AGENTIC_VDESKTOP_GUI_PORT=8795 \
AGENTIC_VDESKTOP_BROWSER_PORT=9345 \
AGENTIC_VDESKTOP_PROFILE="$HOME/.cache/my-agentic-vdesktop" \
./run-agentic-browser-vdesktop.sh start
```

Custom display/size:

```bash
AGENTIC_VDESKTOP_DISPLAY=:79 \
AGENTIC_VDESKTOP_GEOMETRY=1920x1080 \
./run-agentic-browser-vdesktop.sh start
```

Custom Xephyr depth:

```bash
AGENTIC_VDESKTOP_MODE=xephyr \
AGENTIC_VDESKTOP_XEPHYR_DEPTH=16/16 \
./run-agentic-browser-vdesktop.sh start
```

Implementation details:

- The script starts a separate tmux session named `agentic-browser-vdesktop`.
- It starts the virtual display if needed.
- It exports `DISPLAY` only inside that tmux session.
- It starts `embedded_agentic_browser/run.sh` with isolated GUI/CDP ports.
- On stop, it also kills Chrome processes using the isolated profile directory.
- For headless mode it exports:
  `EMBEDDED_AGENTIC_CHROME_ARGS="--headless=new --window-size=WIDTH,HEIGHT"`.
- The Chrome driver reads `EMBEDDED_AGENTIC_CHROME_ARGS` and appends those flags
  when launching Chrome.

## Development Notes

- Keep `8791` as the main implementation.
- Keep `8789` only as the older prototype/reference.
- Add new browser capabilities in `embedded_agentic_browser/` first.
- Add tests whenever changing safety policy, autonomous actions, or endpoints.
- Use `apply_patch` for manual edits.
- Commit after edits.
