let state = {
  targets: [],
  selectedTargetId: "",
  snapshot: null,
  viewport: null,
};

const $ = (id) => document.getElementById(id);

function log(message, payload) {
  const item = document.createElement("div");
  item.className = "log-item";
  const time = new Date().toLocaleTimeString();
  item.textContent = payload ? `[${time}] ${message}: ${JSON.stringify(payload)}` : `[${time}] ${message}`;
  $("eventLog").prepend(item);
}

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

function shortUrl(url) {
  if (!url) return "";
  return url.length > 130 ? `${url.slice(0, 110)}...${url.slice(-16)}` : url;
}

async function refreshStatus() {
  const data = await api("/api/status");
  state.targets = data.targets || [];
  $("chromeStatus").textContent = "connected";
  $("chromeStatus").className = "pill ok";
  $("browserPort").textContent = `Chrome ${data.browser_port}`;
  $("modelInfo").textContent = `${data.model} / ${data.reasoning_effort}`;
  renderTabs();
}

function renderTabs() {
  const root = $("tabsList");
  root.innerHTML = "";
  if (!state.targets.length) {
    root.textContent = "No tabs.";
    return;
  }
  state.targets.forEach((target) => {
    const div = document.createElement("div");
    div.className = `tab-item ${target.id === state.selectedTargetId ? "active" : ""}`;
    div.innerHTML = `
      <div class="tab-title">${escapeHtml(target.title || "(untitled)")}</div>
      <div class="tab-url">${escapeHtml(shortUrl(target.url || ""))}</div>
    `;
    div.addEventListener("click", () => {
      state.selectedTargetId = target.id;
      renderTabs();
      inspect();
    });
    root.appendChild(div);
  });
  if (!state.selectedTargetId && state.targets[0]) {
    state.selectedTargetId = state.targets[0].id;
    renderTabs();
  }
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  $("snapshotMeta").textContent = `${snapshot.title || "(untitled)"} - ${snapshot.url || ""}`;
  const policy = snapshot.policy || {};
  $("policyBox").innerHTML = `
    <strong>Policy:</strong>
    ${policy.is_public_domain ? "public-domain host" : policy.is_shadow_library ? "shadow-library host" : "regular host"}
    ${policy.allowed ? "<span class='pill ok'>allowed</span>" : "<span class='pill warn'>blocked next action</span>"}
    ${policy.stop_reason ? `<div>${escapeHtml(policy.stop_reason)}</div>` : ""}
  `;
  renderCards(snapshot.cards || []);
  renderLinks(snapshot.downloadish || []);
  $("textSample").textContent = (snapshot.textSample || []).join("\n");
}

function renderCards(cards) {
  const root = $("cardsList");
  root.innerHTML = "";
  if (!cards.length) {
    root.textContent = "No structured book cards detected.";
    return;
  }
  cards.slice(0, 40).forEach((card) => {
    const div = document.createElement("div");
    div.className = "card-item";
    div.innerHTML = `
      <div class="card-index">${card.index}</div>
      <div>
        <div class="card-title">${escapeHtml(card.title || "(no title)")}</div>
        <div class="card-meta">${escapeHtml((card.authors || []).join("; "))}</div>
        <div class="card-meta">${escapeHtml([card.year, card.lang, card.file].filter(Boolean).join(" / "))}</div>
      </div>
    `;
    root.appendChild(div);
  });
}

function renderLinks(links) {
  const root = $("linksList");
  root.innerHTML = "";
  if (!links.length) {
    root.textContent = "No download-looking links detected.";
    return;
  }
  links.slice(0, 40).forEach((link) => {
    const div = document.createElement("div");
    div.className = "link-item";
    const openButton = document.createElement("button");
    openButton.className = "secondary";
    openButton.textContent = "Guarded Open";
    openButton.addEventListener("click", () => guardedOpen(link.href));
    div.innerHTML = `
      <div>
        <div class="card-title">${escapeHtml(link.text || "(link)")}</div>
        <div class="link-url">${escapeHtml(shortUrl(link.href))}</div>
      </div>
    `;
    div.appendChild(openButton);
    root.appendChild(div);
  });
}

async function openUrl(url, guarded = false) {
  const endpoint = guarded ? "/api/guarded-open" : "/api/open";
  const data = await api(endpoint, {
    method: "POST",
    body: JSON.stringify({url, bring_to_front: true}),
  });
  log(guarded ? "guarded open" : "open", data);
  await refreshStatus();
}

async function guardedOpen(url) {
  try {
    await openUrl(url, true);
  } catch (error) {
    log("blocked", error.message);
    alert(error.message);
  }
}

async function inspect() {
  const query = state.selectedTargetId ? `?target_id=${encodeURIComponent(state.selectedTargetId)}` : "";
  const snapshot = await api(`/api/snapshot${query}`);
  renderSnapshot(snapshot);
  log("snapshot", {title: snapshot.title, url: snapshot.url});
}

async function captureViewport() {
  if (!state.selectedTargetId) await refreshStatus();
  const query = state.selectedTargetId ? `?target_id=${encodeURIComponent(state.selectedTargetId)}&quality=72` : "?quality=72";
  const data = await api(`/api/viewport${query}`);
  state.viewport = data;
  const image = $("viewportImage");
  image.src = data.screenshot;
  image.style.display = "block";
  $("viewportEmpty").style.display = "none";
  const metrics = data.metrics || {};
  const viewport = metrics.viewport || {};
  const scroll = metrics.scroll || {};
  $("viewportMeta").textContent = `${metrics.title || "(untitled)"} - ${metrics.url || ""} | ${viewport.width || "?"}x${viewport.height || "?"} | scroll ${Math.round(scroll.y || 0)}/${Math.round(scroll.height || 0)}`;
  log("viewport", {title: metrics.title, url: metrics.url});
}

async function browserAction(action, payload = {}) {
  if (!state.selectedTargetId) await refreshStatus();
  const data = await api("/api/browser-action", {
    method: "POST",
    body: JSON.stringify({
      target_id: state.selectedTargetId,
      action,
      payload,
    }),
  });
  log(`browser ${action}`, data.result);
  await new Promise((resolve) => setTimeout(resolve, action === "wait" ? 250 : 700));
  await captureViewport();
  if (["reload", "navigate", "back", "forward", "click"].includes(action)) {
    setTimeout(() => refreshStatus().catch((error) => log("refresh error", error.message)), 900);
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

async function askCodex() {
  if (!state.selectedTargetId) await refreshStatus();
  $("codexBtn").disabled = true;
  $("decisionBox").textContent = "Running codex exec...";
  try {
    const data = await api("/api/codex-decision", {
      method: "POST",
      body: JSON.stringify({
        target_id: state.selectedTargetId,
        goal: $("goalInput").value,
      }),
    });
    $("decisionBox").textContent = JSON.stringify(data.decision, null, 2);
    renderSnapshot(data.snapshot);
    log("codex decision", data.decision);
  } catch (error) {
    $("decisionBox").textContent = error.message;
    log("codex error", error.message);
  } finally {
    $("codexBtn").disabled = false;
  }
}

async function runAutopilot() {
  if (!state.selectedTargetId) await refreshStatus();
  $("autopilotBtn").disabled = true;
  $("decisionBox").textContent = "Running monitored autopilot...";
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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.addEventListener("DOMContentLoaded", () => {
  $("refreshTabsBtn").addEventListener("click", refreshStatus);
  $("inspectBtn").addEventListener("click", inspect);
  $("codexBtn").addEventListener("click", askCodex);
  $("autopilotBtn").addEventListener("click", runAutopilot);
  $("captureBtn").addEventListener("click", captureViewport);
  $("viewportImage").addEventListener("click", viewportClick);
  $("scrollUpBtn").addEventListener("click", () => browserAction("scroll", {delta_y: -700}));
  $("scrollDownBtn").addEventListener("click", () => browserAction("scroll", {delta_y: 700}));
  $("reloadBtn").addEventListener("click", () => browserAction("reload", {ignore_cache: false}));
  $("backBtn").addEventListener("click", () => browserAction("back"));
  $("forwardBtn").addEventListener("click", () => browserAction("forward"));
  $("openBtn").addEventListener("click", () => openUrl($("urlInput").value, false));
  $("guardedOpenBtn").addEventListener("click", () => guardedOpen($("urlInput").value));
  document.querySelectorAll("[data-url]").forEach((button) => {
    button.addEventListener("click", () => {
      $("urlInput").value = button.dataset.url;
      openUrl(button.dataset.url, false);
    });
  });
  refreshStatus().catch((error) => {
    $("chromeStatus").textContent = "error";
    $("chromeStatus").className = "pill warn";
    log("status error", error.message);
  });
});
