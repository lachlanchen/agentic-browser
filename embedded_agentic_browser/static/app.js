let state = {
  targets: [],
  selectedTargetId: "",
  snapshot: null,
  viewport: null,
  lastDecision: null,
  lastAutonomousRun: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.policy?.stop_reason || `HTTP ${response.status}`);
  }
  return data;
}

function log(message, payload) {
  const item = document.createElement("div");
  item.className = "log-item";
  const stamp = new Date().toLocaleTimeString();
  item.textContent = payload ? `[${stamp}] ${message}: ${JSON.stringify(payload)}` : `[${stamp}] ${message}`;
  $("eventLog").prepend(item);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortUrl(url) {
  if (!url) return "";
  return url.length > 130 ? `${url.slice(0, 108)}...${url.slice(-18)}` : url;
}

async function refreshStatus() {
  const data = await api("/api/status");
  state.targets = data.targets || [];
  $("chromeStatus").textContent = "connected";
  $("chromeStatus").className = "pill ok";
  $("browserPort").textContent = `Chrome CDP ${data.browser_port}`;
  $("modelInfo").textContent = `${data.model} / ${data.reasoning_effort}`;
  $("logPath").textContent = data.action_log || "";
  renderTabs();
  return data;
}

function renderTabs() {
  const root = $("tabsList");
  root.innerHTML = "";
  if (!state.targets.length) {
    root.textContent = "No browser tabs detected.";
    return;
  }
  if (!state.selectedTargetId || !state.targets.some((target) => target.id === state.selectedTargetId)) {
    state.selectedTargetId = state.targets[0].id;
  }
  for (const target of state.targets) {
    const div = document.createElement("div");
    div.className = `tab-item ${target.id === state.selectedTargetId ? "active" : ""}`;
    div.innerHTML = `
      <div class="tab-title">${escapeHtml(target.title || "(untitled)")}</div>
      <div class="tab-url">${escapeHtml(shortUrl(target.url || ""))}</div>
    `;
    div.addEventListener("click", () => {
      state.selectedTargetId = target.id;
      renderTabs();
      captureViewport().catch((error) => log("capture error", error.message));
    });
    root.appendChild(div);
  }
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  $("snapshotMeta").textContent = `${snapshot.title || "(untitled)"} - ${shortUrl(snapshot.url || "")}`;
  const policy = snapshot.policy || {};
  const mode = policy.mode || (policy.is_shadow_library ? "shadow-library" : "regular");
  $("policyBox").innerHTML = `
    <strong>${escapeHtml(mode)}</strong>
    ${policy.allowed ? "<span class='pill ok'>allowed</span>" : "<span class='pill warn'>blocked</span>"}
    <div>${escapeHtml(policy.host || "")}</div>
    ${policy.stop_reason ? `<div>${escapeHtml(policy.stop_reason)}</div>` : ""}
  `;
  renderCards(snapshot.cards || []);
  renderLinks(snapshot.downloadish || []);
  renderInteractive(snapshot.interactive || []);
  $("textSample").textContent = (snapshot.textSample || []).join("\n");
}

function renderInteractive(elements) {
  const root = $("interactiveList");
  root.innerHTML = "";
  if (!elements.length) {
    root.textContent = "No visible interactive elements detected.";
    return;
  }
  for (const element of elements.slice(0, 42)) {
    const div = document.createElement("div");
    div.className = `element-item ${element.disabled ? "disabled" : ""}`;
    const label = element.text || element.placeholder || element.value || element.href || "(no label)";
    div.innerHTML = `
      <div class="card-index">${escapeHtml(element.index)}</div>
      <div>
        <div class="card-title">${escapeHtml(`${element.tag}${element.type ? `[${element.type}]` : ""}: ${label}`)}</div>
        <div class="card-meta">${escapeHtml(element.selector || "")}</div>
        ${element.href ? `<div class="link-url">${escapeHtml(shortUrl(element.href))}</div>` : ""}
      </div>
      <div class="element-actions">
        <button class="secondary" data-action="click">Click</button>
        <button class="secondary" data-action="type">Type</button>
      </div>
    `;
    div.querySelector("[data-action=click]").addEventListener("click", () => {
      browserAction("click_selector", {selector: element.selector}).catch((error) => {
        log("element click error", error.message);
        alert(error.message);
      });
    });
    div.querySelector("[data-action=type]").addEventListener("click", () => {
      browserAction("type_selector", {
        selector: element.selector,
        text: $("typeInput").value,
        clear_first: true,
      }).catch((error) => {
        log("element type error", error.message);
        alert(error.message);
      });
    });
    root.appendChild(div);
  }
}

function renderCards(cards) {
  const root = $("cardsList");
  root.innerHTML = "";
  if (!cards.length) {
    root.textContent = "No structured cards detected.";
    return;
  }
  for (const card of cards.slice(0, 28)) {
    const div = document.createElement("div");
    div.className = "card-item";
    div.innerHTML = `
      <div class="card-index">${escapeHtml(card.index)}</div>
      <div>
        <div class="card-title">${escapeHtml(card.title || "(no title)")}</div>
        <div class="card-meta">${escapeHtml((card.authors || []).join("; "))}</div>
        <div class="card-meta">${escapeHtml([card.year, card.lang, card.file].filter(Boolean).join(" / "))}</div>
      </div>
    `;
    root.appendChild(div);
  }
}

function renderLinks(links) {
  const root = $("linksList");
  root.innerHTML = "";
  if (!links.length) {
    root.textContent = "No download-looking links detected.";
    return;
  }
  for (const link of links.slice(0, 28)) {
    const div = document.createElement("div");
    div.className = "link-item";
    div.innerHTML = `
      <div>
        <div class="card-title">${escapeHtml(link.text || "(link)")}</div>
        <div class="link-url">${escapeHtml(shortUrl(link.href))}</div>
      </div>
      <div class="element-actions">
        <button class="secondary" data-action="open">Guarded</button>
        <button class="secondary" data-action="download">Download</button>
      </div>
    `;
    div.querySelector("[data-action=open]").addEventListener("click", () => guardedOpen(link.href));
    div.querySelector("[data-action=download]").addEventListener("click", () => downloadUrl(link.href));
    root.appendChild(div);
  }
}

async function downloadUrl(url) {
  try {
    const data = await api("/api/download", {
      method: "POST",
      body: JSON.stringify({url}),
    });
    log("download", data);
    $("decisionBox").textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    log("download blocked/error", error.message);
    alert(error.message);
  }
}

async function openUrl(url, guarded = false) {
  const endpoint = guarded ? "/api/guarded-open" : "/api/open";
  const data = await api(endpoint, {
    method: "POST",
    body: JSON.stringify({url, bring_to_front: true}),
  });
  const openedTargetId = data.target?.id || "";
  state.selectedTargetId = openedTargetId || state.selectedTargetId;
  log(guarded ? "guarded open" : "open", {url: data.url, policy: data.policy?.mode});
  await waitForOpenedTarget(openedTargetId, data.url);
  await captureLoadedViewport(data.url);
  return data;
}

function urlsMatchExpected(actualUrl, expectedUrl) {
  if (!actualUrl || actualUrl === "about:blank") return false;
  if (!expectedUrl) return true;
  try {
    const actual = new URL(actualUrl);
    const expected = new URL(expectedUrl, location.href);
    return actual.href === expected.href || (
      actual.hostname === expected.hostname &&
      actual.pathname === expected.pathname
    );
  } catch {
    return actualUrl.includes(expectedUrl);
  }
}

async function waitForOpenedTarget(openedTargetId, expectedUrl, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  let matchedTarget = null;
  while (Date.now() < deadline) {
    const status = await refreshStatus();
    matchedTarget = (status.targets || []).find((target) => (
      (openedTargetId && target.id === openedTargetId) ||
      urlsMatchExpected(target.url, expectedUrl)
    ));
    if (matchedTarget) {
      state.selectedTargetId = matchedTarget.id;
      renderTabs();
      return matchedTarget;
    }
    if (openedTargetId) state.selectedTargetId = openedTargetId;
    await delay(400);
  }
  if (openedTargetId) {
    state.selectedTargetId = openedTargetId;
    renderTabs();
  }
  return matchedTarget;
}

function captureMatchesExpected(data, expectedUrl) {
  const actualUrl = data?.snapshot?.url || data?.viewport?.metrics?.url || "";
  return urlsMatchExpected(actualUrl, expectedUrl);
}

async function captureLoadedViewport(expectedUrl, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs;
  let lastCapture = null;
  while (Date.now() < deadline) {
    await delay(lastCapture ? 700 : 900);
    lastCapture = await captureViewport();
    if (captureMatchesExpected(lastCapture, expectedUrl)) return lastCapture;
    await refreshStatus();
  }
  return lastCapture;
}

async function guardedOpen(url) {
  try {
    return await openUrl(url, true);
  } catch (error) {
    log("blocked", error.message);
    alert(error.message);
    throw error;
  }
}

async function inspect() {
  const query = state.selectedTargetId ? `?target_id=${encodeURIComponent(state.selectedTargetId)}` : "";
  const data = await api(`/api/observe${query}${query ? "&" : "?"}quality=74`);
  renderObservation(data);
  log("observe", {
    title: data.snapshot?.title,
    url: data.snapshot?.url,
    elements: data.snapshot?.interactive?.length || 0,
    cards: data.snapshot?.cards?.length || 0,
  });
  return data.snapshot;
}

function renderViewport(data) {
  state.viewport = data;
  const image = $("viewportImage");
  image.src = data.screenshot;
  image.style.display = "block";
  $("viewportEmpty").style.display = "none";
  const metrics = data.metrics || {};
  const viewport = metrics.viewport || {};
  const scroll = metrics.scroll || {};
  $("viewportMeta").textContent = `${metrics.title || "(untitled)"} - ${shortUrl(metrics.url || "")} | ${viewport.width || "?"}x${viewport.height || "?"} | scroll ${Math.round(scroll.y || 0)}/${Math.round(scroll.height || 0)}`;
}

function renderObservation(data) {
  if (data.target_id) state.selectedTargetId = data.target_id;
  if (data.viewport) renderViewport(data.viewport);
  if (data.snapshot) renderSnapshot(data.snapshot);
}

async function captureViewport() {
  if (!state.selectedTargetId) await refreshStatus();
  const query = state.selectedTargetId ? `?target_id=${encodeURIComponent(state.selectedTargetId)}&quality=74` : "?quality=74";
  const data = await api(`/api/observe${query}`);
  renderObservation(data);
  log("observe", {
    title: data.snapshot?.title,
    url: data.snapshot?.url,
    elements: data.snapshot?.interactive?.length || 0,
    cards: data.snapshot?.cards?.length || 0,
  });
  return data;
}

async function browserAction(action, payload = {}) {
  if (!state.selectedTargetId) await refreshStatus();
  const data = await api("/api/action", {
    method: "POST",
    body: JSON.stringify({
      target_id: state.selectedTargetId,
      action,
      payload,
    }),
  });
  log(`browser ${action}`, data.result);
  await delay(action === "wait" ? 250 : 750);
  await captureViewport();
  if (["reload", "navigate", "back", "forward", "click", "click_selector", "click_text", "type_selector"].includes(action)) {
    setTimeout(() => refreshStatus().catch((error) => log("refresh error", error.message)), 800);
  }
  return data;
}

function viewportClick(event) {
  if (!state.viewport) return;
  const image = $("viewportImage");
  const rect = image.getBoundingClientRect();
  const metrics = state.viewport.metrics || {};
  const viewport = metrics.viewport || {};
  const x = ((event.clientX - rect.left) / rect.width) * (viewport.width || image.naturalWidth);
  const y = ((event.clientY - rect.top) / rect.height) * (viewport.height || image.naturalHeight);
  browserAction("click", {x, y}).catch((error) => {
    log("click error", error.message);
    alert(error.message);
  });
}

async function agentStep() {
  if (!state.selectedTargetId) await refreshStatus();
  $("agentStepBtn").disabled = true;
  $("decisionBox").textContent = "Running codex exec...";
  try {
    const data = await api("/api/agent-step", {
      method: "POST",
      body: JSON.stringify({
        target_id: state.selectedTargetId,
        goal: $("goalInput").value,
      }),
    });
    state.lastDecision = data.decision;
    $("decisionBox").textContent = JSON.stringify(data.decision, null, 2);
    renderSnapshot(data.snapshot);
    log("codex step", data.decision);
  } catch (error) {
    $("decisionBox").textContent = error.message;
    log("codex error", error.message);
  } finally {
    $("agentStepBtn").disabled = false;
  }
}

async function executeLastDecision() {
  const decision = state.lastDecision;
  if (!decision) {
    alert("No Codex decision to execute.");
    return;
  }
  const action = decision.action;
  if (action === "open_url") {
    await browserAction("navigate", {url: decision.next_url});
  } else if (action === "scroll") {
    await browserAction("scroll", {delta_y: Number(decision.scroll_delta_y || 700)});
  } else if (action === "wait") {
    await browserAction("wait", {seconds: Number(decision.wait_seconds || 1)});
  } else {
    log("decision not executable", decision);
  }
}

async function runAutopilot() {
  if (!state.selectedTargetId) await refreshStatus();
  $("autopilotBtn").disabled = true;
  $("decisionBox").textContent = "Running bounded autopilot...";
  try {
    const data = await api("/api/autopilot", {
      method: "POST",
      body: JSON.stringify({
        target_id: state.selectedTargetId,
        goal: $("goalInput").value,
        max_steps: Number($("maxStepsInput").value || 3),
      }),
    });
    $("decisionBox").textContent = JSON.stringify(data, null, 2);
    log("autopilot", {status: data.status, steps: data.steps?.length || 0});
    await refreshStatus();
    await inspect();
    await captureViewport();
  } catch (error) {
    $("decisionBox").textContent = error.message;
    log("autopilot error", error.message);
  } finally {
    $("autopilotBtn").disabled = false;
  }
}

function renderAutonomousRun(data) {
  state.lastAutonomousRun = data;
  const plan = data.plan || {};
  const final = data.final_decision || {};
  const finalPage = data.final_snapshot?.page || {};
  const planLines = (plan.plan || []).map((item, index) => `${index + 1}. ${item}`);
  const stepLines = (data.step_records || []).map((record) => {
    const decision = record.decision || {};
    const execution = record.execution || {};
    const action = decision.action || "(none)";
    const status = execution.status || "pending";
    const reason = decision.reason ? ` - ${decision.reason}` : "";
    return `step ${record.step}: ${action} -> ${status}${reason}`;
  });
  $("autonomousStatus").textContent = data.status || "complete";
  $("autonomousStatus").className = data.ok ? "pill ok" : "pill warn";
  $("autonomousBox").textContent = [
    `status: ${data.status}`,
    `run: ${data.run_id}`,
    `steps: ${data.steps}`,
    `log: ${data.log_path}`,
    data.inferred_start_url ? `start: ${data.inferred_start_url}` : "",
    final.selected_title ? `selected: ${final.selected_title}${final.selected_author ? ` | ${final.selected_author}` : ""}${final.selected_language ? ` | ${final.selected_language}` : ""}` : "",
    final.extracted_answer ? `answer: ${final.extracted_answer}` : "",
    final.reason ? `final reason: ${final.reason}` : "",
    finalPage.url ? `final page: ${finalPage.url}` : "",
    "",
    "plan:",
    ...(planLines.length ? planLines : ["(no plan returned)"]),
    "",
    plan.risk_notes ? `risk notes: ${plan.risk_notes}` : "",
    plan.done_signal ? `done signal: ${plan.done_signal}` : "",
    "",
    "executed steps:",
    ...(stepLines.length ? stepLines : ["(no steps recorded)"]),
  ].filter((line) => line !== "").join("\n");
}

async function runAutonomousSurf() {
  if (!state.selectedTargetId) await refreshStatus();
  $("autonomousRunBtn").disabled = true;
  $("autonomousStatus").textContent = "running";
  $("autonomousStatus").className = "pill";
  $("autonomousBox").textContent = "Planning with codex exec, then running one browser-control decision per step...";
  try {
    const data = await api("/api/autonomous-run", {
      method: "POST",
      body: JSON.stringify({
        target_id: state.selectedTargetId,
        start_url: $("autonomousStartUrl").value.trim(),
        goal: $("goalInput").value,
        max_steps: Number($("maxStepsInput").value || 8),
        make_plan: true,
      }),
    });
    state.selectedTargetId = data.target_id || state.selectedTargetId;
    state.lastDecision = data.final_decision || null;
    renderAutonomousRun(data);
    $("decisionBox").textContent = JSON.stringify(data.final_decision || data, null, 2);
    log("autonomous surf", {
      status: data.status,
      steps: data.steps,
      run_id: data.run_id,
      log_path: data.log_path,
    });
    await refreshStatus();
    await captureViewport();
  } catch (error) {
    $("autonomousStatus").textContent = "error";
    $("autonomousStatus").className = "pill warn";
    $("autonomousBox").textContent = error.message;
    log("autonomous error", error.message);
  } finally {
    $("autonomousRunBtn").disabled = false;
  }
}

async function runBookTask() {
  $("runBookTaskBtn").disabled = true;
  $("decisionBox").textContent = "Opening search page, waiting for dynamic results, then running Codex...";
  try {
    const data = await api("/api/run-book-task", {
      method: "POST",
      body: JSON.stringify({
        query: $("bookTaskInput").value,
        source: $("bookTaskSource").value,
        goal: $("goalInput").value,
        max_steps: Number($("maxStepsInput").value || 3),
      }),
    });
    state.selectedTargetId = data.target?.id || state.selectedTargetId;
    state.lastDecision = data.result?.steps?.at(-1)?.decision || null;
    $("decisionBox").textContent = JSON.stringify(data, null, 2);
    if (data.initial_snapshot) renderSnapshot(data.initial_snapshot);
    log("book task", {
      query: data.query,
      status: data.result?.status,
      steps: data.result?.steps?.length || 0,
      cards: data.initial_snapshot?.cards?.length || 0,
    });
    await refreshStatus();
    await captureViewport();
  } catch (error) {
    $("decisionBox").textContent = error.message;
    log("book task error", error.message);
  } finally {
    $("runBookTaskBtn").disabled = false;
  }
}

async function runLibgenInspect() {
  $("libgenInspectBtn").disabled = true;
  $("decisionBox").textContent = "Inspecting LibGen search/detail page, selecting a candidate, then stopping at the links page...";
  try {
    const queryOrUrl = $("bookTaskInput").value.trim() || $("urlInput").value.trim();
    const data = await api("/api/libgen-inspect", {
      method: "POST",
      body: JSON.stringify({
        query_or_url: queryOrUrl,
        goal: $("goalInput").value,
      }),
    });
    state.selectedTargetId = data.target?.id || state.selectedTargetId;
    state.lastDecision = data.decision || null;
    const mirrorLines = (data.mirror_links || []).map((link, index) => {
      const policy = link.policy || {};
      const allowed = policy.allowed ? "allowed" : "blocked";
      return `${index + 1}. ${link.text || "(link)"} - ${allowed} - ${link.href}`;
    });
    $("decisionBox").textContent = [
      `status: ${data.status}`,
      `selected: ${data.selected_card?.title || data.decision?.selected_title || "(none)"}`,
      `author: ${(data.selected_card?.authors || [data.decision?.selected_author]).filter(Boolean).join("; ")}`,
      `links page: ${data.links_snapshot?.url || ""}`,
      data.stop_reason || "",
      "",
      "mirror/link options:",
      ...(mirrorLines.length ? mirrorLines : ["(none detected)"]),
    ].join("\n");
    if (data.links_snapshot) renderSnapshot(data.links_snapshot);
    log("libgen inspect", {
      status: data.status,
      selected: data.selected_card?.title || data.decision?.selected_title,
      links: data.mirror_links?.length || 0,
      url: data.links_snapshot?.url,
    });
    await refreshStatus();
    await captureViewport();
  } catch (error) {
    $("decisionBox").textContent = error.message;
    log("libgen inspect error", error.message);
  } finally {
    $("libgenInspectBtn").disabled = false;
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

document.addEventListener("DOMContentLoaded", () => {
  $("refreshTabsBtn").addEventListener("click", refreshStatus);
  $("inspectBtn").addEventListener("click", inspect);
  $("captureBtn").addEventListener("click", captureViewport);
  $("agentStepBtn").addEventListener("click", agentStep);
  $("executeDecisionBtn").addEventListener("click", executeLastDecision);
  $("autopilotBtn").addEventListener("click", runAutopilot);
  $("runBookTaskBtn").addEventListener("click", runBookTask);
  $("libgenInspectBtn").addEventListener("click", runLibgenInspect);
  $("autonomousRunBtn").addEventListener("click", runAutonomousSurf);
  $("viewportImage").addEventListener("click", viewportClick);
  $("scrollUpBtn").addEventListener("click", () => browserAction("scroll", {delta_y: -700}));
  $("scrollDownBtn").addEventListener("click", () => browserAction("scroll", {delta_y: 700}));
  $("reloadBtn").addEventListener("click", () => browserAction("reload", {ignore_cache: false}));
  $("backBtn").addEventListener("click", () => browserAction("back"));
  $("forwardBtn").addEventListener("click", () => browserAction("forward"));
  $("typeBtn").addEventListener("click", () => browserAction("type", {text: $("typeInput").value}));
  $("enterBtn").addEventListener("click", () => browserAction("key", {key: "Enter"}));
  $("openBtn").addEventListener("click", () => openUrl($("urlInput").value, false).catch((error) => alert(error.message)));
  $("guardedOpenBtn").addEventListener("click", () => guardedOpen($("urlInput").value).catch(() => undefined));
  document.querySelectorAll("[data-url]").forEach((button) => {
    button.addEventListener("click", () => {
      $("urlInput").value = button.dataset.url;
      openUrl(button.dataset.url, false).catch((error) => {
        log("open error", error.message);
        alert(error.message);
      });
    });
  });
  refreshStatus()
    .then(() => captureViewport())
    .catch((error) => {
      $("chromeStatus").textContent = "error";
      $("chromeStatus").className = "pill warn";
      log("status error", error.message);
    });
});
