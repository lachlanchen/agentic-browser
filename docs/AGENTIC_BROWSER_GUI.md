# Agentic Browser GUI

`agentic_browser.py` is a local GUI controller for step-by-step book-search
automation. It drives a real Chrome instance through Chrome DevTools Protocol
and exposes the page state in a browser UI.

## Goals

- Open and inspect book search pages in a controlled Chrome profile.
- See the selected Chrome tab inside the GUI through a live CDP screenshot.
- Click, scroll, reload, and navigate the selected tab from the GUI.
- Extract visible book cards, links, download-looking links, and text snippets.
- Ask `codex exec` for a structured next-step recommendation.
- Run a bounded monitored autopilot loop where Codex chooses one safe step at a
  time and the local guard policy enforces safety.
- Make decisions at each step instead of blindly clicking through pages.
- Stop before unsafe or non-public-domain download/mirror URLs.

## Run

```bash
./run-agentic-browser-gui.sh
```

Defaults:

```text
GUI: http://127.0.0.1:8789
Controlled Chrome DevTools: http://127.0.0.1:9223
Codex model: gpt-5.4-mini
Reasoning effort: low
```

Run in tmux:

```bash
tmux new-session -d -s agentic-browser-gui './run-agentic-browser-gui.sh'
```

Then open:

```bash
http://127.0.0.1:8789
```

## Workflow

1. Open a search/detail/source page from the GUI.
2. Select the Chrome tab in the `Tabs` panel.
3. Click `Capture` to render the tab inside the GUI.
4. Click inside the screenshot, scroll, reload, go back/forward, or inspect.
5. Click `Inspect` to extract book cards and links.
6. Use `Ask Codex` to get a structured candidate decision.
7. Use `Run Autopilot` for bounded one-step-at-a-time steering.
8. Use `Guarded Open` for any next URL.

## Embedded Browser Model

The GUI does not iframe the remote website. Many real targets, including Figma,
BioRender, and some book sites, block iframe embedding with CSP or
`X-Frame-Options`. Instead, the app renders the controlled Chrome tab as a live
CDP screenshot:

```text
Chrome tab -> Page.captureScreenshot -> GUI image viewport
GUI click -> Input.dispatchMouseEvent -> Chrome tab
GUI scroll/reload/back/forward -> CDP action -> Chrome tab
```

This works with authenticated or complex sites as long as the controlled Chrome
profile has the required login/session. It does not bypass login, paywalls, or
site access controls.

## Monitored Autopilot

`Run Autopilot` performs a bounded loop:

1. Snapshot the current tab.
2. Ask `codex exec` for exactly one next action.
3. Enforce local guard policy.
4. Execute only safe actions.
5. Log the decision and action.
6. Repeat up to the configured step limit.

Autopilot action vocabulary:

```text
select, open_url, scroll, wait, hold, stop
```

It intentionally avoids arbitrary JavaScript execution or unbounded clicking.
For LibGen and other shadow-library hosts, it can inspect search/detail pages
but cannot proceed to mirror/download/direct-file pages.

## Safety Policy

The GUI supports LibGen as a search/candidate-inspection example, but guarded
actions block shadow-library mirror/download/direct-file URLs.

Allowed examples:

```text
https://libgen.pw/search?query=Gone+with+the+Wind&collection=libgen
https://libgen.pw/links/<record-id>
```

Blocked examples:

```text
shadow-library mirror URLs
direct PDF/EPUB/MOBI/ZIP/RAR URLs on non-public-domain hosts
download/get/ipfs/torrent-looking URLs on shadow-library hosts
```

Public-domain/open hosts such as Wikisource, CText, NDL, Aozora, Gutenberg,
Standard Ebooks, and Archive.org are treated as public-domain candidates for
guarded navigation.

## Codex Wrapper

The `Ask Codex` button runs:

```text
codex exec --ephemeral --model gpt-5.4-mini -c model_reasoning_effort="low" -s read-only
```

The prompt includes:

- current page URL/title/policy
- visible book cards
- download-looking links
- text snippet
- the user goal from the GUI text box

Codex returns JSON:

```json
{
  "action": "select | open_next | hold | stop",
  "selected_index": 0,
  "selected_title": "...",
  "selected_author": "...",
  "selected_language": "...",
  "next_url": "",
  "safety_stop": false,
  "reason": "..."
}
```

The autopilot wrapper returns similar JSON plus step/action fields. Every step
is appended to `library/agentic-browser/actions.jsonl`.

## Logs

Every open, blocked open, and Codex decision is appended to:

```text
library/agentic-browser/actions.jsonl
```

## Example

For _Gone with the Wind_:

1. Open `LibGen: GWT EN`.
2. Inspect the page.
3. Ask Codex to choose the best English candidate.
4. Repeat for Chinese and Japanese.
5. Do not use guarded open for mirror/download pages unless the source is
   clearly public-domain/open.

## TDV Checks

Run local tests:

```bash
python3 -m unittest test_agentic_browser.py
python3 -m py_compile agentic_browser.py
```

The tests cover:

- LibGen search/detail URLs are inspectable.
- LibGen download/mirror URLs are blocked.
- Non-public direct binary URLs are blocked.
- Public-domain host URLs are allowed.
- Autopilot stops on a `select` decision.
- Autopilot blocks unsafe Codex-proposed next URLs.
