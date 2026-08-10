const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败（${response.status}）`);
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

let toastTimer;
function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { element.className = "toast"; }, 3800);
}

function setBadge(element, text, state = "") {
  element.textContent = text;
  element.className = `badge${state ? ` ${state}` : ""}`;
}

async function loadAll() {
  $("#refreshButton").disabled = true;
  try {
    const [preflight, browser, jobsPayload] = await Promise.all([api("/api/preflight"), api("/api/browser-setup/status"), api("/api/jobs")]);
    renderPreflight(preflight);
    renderBrowser(browser);
    renderJobs(jobsPayload.jobs || []);
    const blockedJobs = (jobsPayload.jobs || []).filter((job) => job.status === "human_required");
    const ready = Boolean(preflight.ready) && blockedJobs.length === 0;
    $("#overallPulse").className = `pulse ${ready ? "ready" : "blocked"}`;
    $("#overallTitle").textContent = ready ? "当前无需人工处理" : "有项目需要你处理";
    $("#overallDetail").textContent = ready ? "可以回到 Hermes 继续对话。" : `${preflight.blocking_count || 0} 个环境阻塞，${blockedJobs.length} 个暂停任务。`;
  } catch (error) {
    $("#overallPulse").className = "pulse blocked";
    $("#overallTitle").textContent = "无法读取服务状态";
    $("#overallDetail").textContent = error.message;
    toast(error.message, true);
  } finally { $("#refreshButton").disabled = false; }
}

function renderPreflight(data) {
  setBadge($("#preflightBadge"), data.ready ? "可运行" : `${data.blocking_count || 0} 项阻塞`, data.ready ? "ready" : "blocked");
  const checks = Array.isArray(data.checks) ? data.checks : [];
  $("#checkList").innerHTML = checks.length ? checks.map((check) => {
    const blocked = check.level === "blocking" || check.status === "error" || check.ready === false;
    const ready = !blocked && (check.status === "ok" || check.ready === true);
    return `<div class="check"><span class="check-dot ${blocked ? "blocked" : ready ? "ready" : ""}"></span><div><strong>${escapeHtml(check.label || check.key || "检查项")}</strong><span>${escapeHtml(check.detail || check.status || "")}</span></div></div>`;
  }).join("") : '<div class="empty">暂无检查结果</div>';
}

function renderBrowser(data) {
  setBadge($("#browserBadge"), data.reachable ? "已连接" : "未连接", data.reachable ? "ready" : "blocked");
  $("#browserDetail").textContent = data.detail || "未返回浏览器状态";
  const sites = data.sites || {};
  $("#siteList").innerHTML = ["amazon", "1688"].map((site) => {
    const item = sites[site] || {};
    const ready = Boolean(item.ready || item.configured || item.status === "ready");
    return `<article class="site-card"><div class="site-top"><strong>${site === "amazon" ? "Amazon US" : "1688"}</strong><span class="badge ${ready ? "ready" : "blocked"}">${ready ? "登录态可用" : "需要检查"}</span></div><p>${escapeHtml(item.message || item.detail || "需要时可重新登录并保存状态。")}</p><div class="site-actions"><button class="button ghost" data-login="${site}">打开登录页</button><button class="button primary" data-save-login="${site}">已完成，保存登录态</button></div></article>`;
  }).join("");
}

function renderJobs(jobs) {
  const blocked = jobs.filter((job) => job.status === "human_required");
  setBadge($("#jobsBadge"), `${blocked.length} 个`, blocked.length ? "blocked" : "ready");
  $("#jobsList").innerHTML = blocked.length ? blocked.map((job) => `<article class="job"><div class="job-top"><span class="job-code">${escapeHtml(job.id)}</span><span class="badge blocked">等待人工</span></div><p><strong>${escapeHtml(job.config?.keyword || job.config?.category || "选品任务")}</strong></p><p>${escapeHtml(job.error || job.message || "请完成页面提示的登录或验证码。")}</p><div class="job-actions"><button class="button primary" data-resume="${escapeHtml(job.id)}">我已处理，继续任务</button></div></article>`).join("") : '<div class="empty">没有暂停中的任务。处理完登录后，可以回到 Hermes 继续。</div>';
}

document.addEventListener("click", async (event) => {
  const loginButton = event.target.closest("[data-login]");
  const saveButton = event.target.closest("[data-save-login]");
  const resumeButton = event.target.closest("[data-resume]");
  const button = loginButton || saveButton || resumeButton;
  if (!button) return;
  button.disabled = true;
  try {
    if (loginButton) {
      const result = await api("/api/browser-setup", { method: "POST", body: JSON.stringify({ action: "open_login", site: loginButton.dataset.login }) });
      toast(result.message || "登录页已打开");
    } else if (saveButton) {
      const result = await api("/api/browser-setup", { method: "POST", body: JSON.stringify({ action: "save_cookies", site: saveButton.dataset.saveLogin }) });
      toast(result.message || "登录态已保存", !result.ok);
      await loadAll();
    } else if (resumeButton) {
      await api(`/api/operator/jobs/${encodeURIComponent(resumeButton.dataset.resume)}/resume`, { method: "POST", body: JSON.stringify({ reason: "用户已在人工处理台完成登录或验证码" }) });
      toast("任务已恢复，可以回到 Hermes 查看进度。");
      await loadAll();
    }
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
});

$("#refreshButton").addEventListener("click", loadAll);
loadAll();
setInterval(loadAll, 15000);
