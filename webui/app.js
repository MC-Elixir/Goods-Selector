const state = {
  preflight: null,
  jobs: [],
  runs: [],
  results: [],
  activeSection: "run",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", () => {
  bindNavigation();
  bindActions();
  refreshAll();
  setInterval(refreshJobs, 4000);
});

function bindNavigation() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".nav-item").forEach((b) => b.classList.remove("active"));
      button.classList.add("active");
      state.activeSection = button.dataset.section;
      $("#runSection").style.display = state.activeSection === "run" ? "grid" : "none";
      $("#resultsSection").style.display = state.activeSection === "settings" ? "none" : "block";
      $("#settingsSection").style.display = state.activeSection === "settings" ? "block" : "none";
    });
  });
}

function bindActions() {
  $("#refreshButton").addEventListener("click", refreshAll);
  $("#loadRunsButton").addEventListener("click", refreshRuns);
  $("#reloadResultsButton").addEventListener("click", refreshResults);
  $("#runButton").addEventListener("click", startRun);
  $("#resetButton").addEventListener("click", () => $("#runForm").reset());
  $("#searchInput").addEventListener("input", renderResults);
  $("#runSelect").addEventListener("change", refreshResults);
}

async function refreshAll() {
  await Promise.all([refreshPreflight(), refreshJobs(), refreshRuns(), refreshPrompt()]);
  await refreshResults();
}

async function refreshPreflight() {
  const data = await getJson("/api/preflight");
  state.preflight = data;
  renderPreflight();
}

async function refreshJobs() {
  const data = await getJson("/api/jobs");
  state.jobs = data.jobs || [];
  renderJobs();
}

async function refreshRuns() {
  const data = await getJson("/api/runs");
  state.runs = data.runs || [];
  renderRuns();
  renderRunSelect();
}

async function refreshResults() {
  const runId = $("#runSelect").value;
  const data = await getJson(`/api/results${runId ? `?run=${encodeURIComponent(runId)}` : ""}`);
  state.results = data.items || [];
  renderResults();
}

async function refreshPrompt() {
  const data = await getJson("/api/prompt");
  $("#promptBox").textContent = data.system_prompt || "";
}

function renderPreflight() {
  const ready = Boolean(state.preflight?.ready);
  $("#sideStatus").textContent = ready ? "Ready" : "Needs Review";
  $("#sideDot").className = `status-dot ${ready ? "ready" : "error"}`;
  $("#agentMetric").textContent = "Online";

  const cookie = (state.preflight?.checks || []).find((c) => c.key === "1688_cookies");
  $("#cookieMetric").textContent = cookie?.level === "ok" ? "Healthy" : "Review";

  $("#preflightBadge").className = `badge ${ready ? "ok" : "err"}`;
  $("#preflightBadge").textContent = state.preflight?.summary || "Checking";
  $("#runButton").disabled = !ready;

  const list = $("#preflightList");
  list.innerHTML = "";
  for (const check of state.preflight?.checks || []) {
    const row = document.createElement("div");
    row.className = `check ${check.level}`;
    row.innerHTML = `
      <span class="mark">${check.level === "ok" ? "✓" : "!"}</span>
      <span>${escapeHtml(check.label)}</span>
      <small>${escapeHtml(check.detail)}</small>
    `;
    list.appendChild(row);
  }

  const readyCard = $("#readyCard");
  readyCard.querySelector("strong").textContent = ready ? "Ready to run" : "Action required";
  readyCard.querySelector("p").textContent = ready
    ? "All blocking checks passed. Start a new sourcing run when ready."
    : "Resolve the failed preflight items before launching a formal run.";
}

function renderJobs() {
  const list = $("#jobList");
  list.innerHTML = "";
  const jobs = state.jobs.slice(0, 5);
  if (!jobs.length) {
    list.innerHTML = `<div class="job"><span class="job-dot"></span><div><strong>No active jobs</strong><span>Start an agent run to see progress here.</span></div></div>`;
    return;
  }
  for (const job of jobs) {
    const row = document.createElement("div");
    row.className = `job ${job.status}`;
    const meta = `${job.config.category} · ${job.config.marketplace} · ${job.config.limit}`;
    row.innerHTML = `
      <span class="job-dot"></span>
      <div>
        <strong>${escapeHtml(job.status.toUpperCase())} · ${escapeHtml(job.message || "")}</strong>
        <span>${escapeHtml(meta)}${job.error ? ` · ${escapeHtml(job.error)}` : ""}</span>
      </div>
      <span class="badge ${job.status === "success" ? "ok" : job.status === "failed" ? "err" : "warn"}">${escapeHtml(job.status)}</span>
    `;
    list.appendChild(row);
  }
}

function renderRuns() {
  const list = $("#exportRunList");
  list.innerHTML = "";
  for (const run of state.runs.slice(0, 5)) {
    const row = document.createElement("div");
    row.className = "export-run";
    row.innerHTML = `
      <span class="job-dot success"></span>
      <div>
        <strong>${escapeHtml(run.id)}</strong>
        <span>${run.count} rows · mock ${run.mock_count} · avg score ${run.avg_score ?? "-"}</span>
      </div>
      ${run.xlsx_file ? `<a class="ghost-button" href="/api/exports/${encodeURIComponent(run.xlsx_file)}">Export</a>` : ""}
    `;
    list.appendChild(row);
  }
}

function renderRunSelect() {
  const select = $("#runSelect");
  const current = select.value;
  select.innerHTML = `<option value="">All exports</option>`;
  for (const run of state.runs) {
    const option = document.createElement("option");
    option.value = run.id;
    option.textContent = `${run.id} (${run.count})`;
    select.appendChild(option);
  }
  select.value = current;
}

function renderResults() {
  const query = $("#searchInput").value.trim().toLowerCase();
  const body = $("#resultsBody");
  body.innerHTML = "";

  const filtered = state.results.filter((item) => {
    if (!query) return true;
    return [item.asin, item.title, item.supplier].some((v) => String(v || "").toLowerCase().includes(query));
  });

  for (const item of filtered) {
    const row = document.createElement("tr");
    const status = item.mock ? "Mock" : item.passed ? "Selected" : "Review";
    const statusClass = item.mock ? "rejected" : item.passed ? "selected" : "review";
    row.innerHTML = `
      <td><button class="save-button ${item.saved ? "saved" : ""}" data-key="${escapeAttr(item.key)}">${item.saved ? "✓" : "+"}</button></td>
      <td><strong>${escapeHtml(item.asin || "-")}</strong></td>
      <td class="title-cell" title="${escapeAttr(item.title || "")}">${escapeHtml(item.title || "-")}</td>
      <td class="supplier-cell" title="${escapeAttr(item.supplier || "")}">${offerLink(item)}</td>
      <td>${money(item.buy_cost_cny, "¥")}</td>
      <td>${percent(item.margin)}</td>
      <td><span class="score-pill">${number(item.score, 0)}</span></td>
      <td><span class="status ${statusClass}">${status}</span></td>
      <td>${item.xlsx_file ? `<a class="ghost-button" href="/api/exports/${encodeURIComponent(item.xlsx_file)}">Download</a>` : "-"}</td>
    `;
    body.appendChild(row);
  }

  $$(".save-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const key = button.dataset.key;
      const saved = !button.classList.contains("saved");
      await postJson("/api/saved", { key, saved });
      const item = state.results.find((r) => r.key === key);
      if (item) item.saved = saved;
      renderResults();
    });
  });

  $("#resultCount").textContent = `${filtered.length} results`;
}

async function startRun() {
  const form = new FormData($("#runForm"));
  const payload = {
    category: form.get("category"),
    marketplace: form.get("marketplace"),
    limit: Number(form.get("limit") || 10),
    no_mock: Boolean(form.get("no_mock")),
    llm_verification: Boolean(form.get("llm_verification")),
  };
  $("#runButton").disabled = true;
  $("#runHint").textContent = "Agent job queued. Progress will appear in Recent Runs.";
  try {
    await postJson("/api/run", payload);
    await refreshJobs();
  } catch (error) {
    $("#runHint").textContent = error.message;
  } finally {
    setTimeout(() => {
      $("#runButton").disabled = !(state.preflight?.ready);
    }, 1200);
  }
}

async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function offerLink(item) {
  const label = escapeHtml(item.supplier || "-");
  if (!item.offer_url) return label;
  return `<a href="${escapeAttr(item.offer_url)}" target="_blank" rel="noreferrer">${label}</a>`;
}

function money(value, prefix = "$") {
  if (value === null || value === undefined || value === "") return "-";
  return `${prefix}${Number(value).toFixed(2)}`;
}

function percent(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function number(value, digits = 1) {
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toFixed(digits);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
