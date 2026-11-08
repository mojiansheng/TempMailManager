/* 日志中心：业务 / 系统 / 前端请求 / 外部请求 四类日志。依赖 window.TM / API。 */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const el = {
    modal: $("#logs-modal"),
    close: $("#logs-close"),
    cancel: $("#logs-cancel"),
    refresh: $("#logs-refresh"),
    level: $("#logs-level"),
    keyword: $("#logs-keyword"),
    list: $("#logs-list"),
    count: $("#logs-count"),
    clear: $("#logs-clear"),
  };

  const ACTION_TEXT = {
    create: "创建", fetch: "抓信", renew: "续期", delete: "删除",
    import: "导入", clear: "清空", server: "异常", system: "系统",
  };
  const LEVEL_TEXT = { info: "信息", warn: "警告", error: "错误" };

  let kind = "business";

  function mailboxLabel(id) {
    if (!id) return "";
    const mb = TM.state.mailboxes.find((m) => m.id === id);
    return mb ? mb.email : `#${id}`;
  }

  function statusClass(status) {
    if (status >= 500) return "fail";
    if (status >= 400) return "warn";
    if (status === 0) return "fail";
    return "ok";
  }

  /* ---------------- 各类型行 ---------------- */
  function businessRow(r) {
    return `
      <div class="log-row">
        <span class="log-time">${TM.esc(r.created_at || "")}</span>
        <span class="log-level ${r.level}">${LEVEL_TEXT[r.level] || r.level}</span>
        <span class="log-action">${ACTION_TEXT[r.action] || TM.esc(r.action || "")}</span>
        <span class="log-msg" title="${TM.esc(r.message || "")}">${TM.esc(r.message || "")}</span>
        <span class="log-target">${TM.esc(mailboxLabel(r.mailbox_id))}</span>
      </div>`;
  }

  function accessRow(r) {
    const path = r.path || "";
    const query = r.query ? `?${r.query}` : "";
    return `
      <details class="log-detail">
        <summary class="log-row log-row-net">
          <span class="log-time">${TM.esc(r.created_at || "")}</span>
          <span class="log-status ${statusClass(r.status)}">${r.status}</span>
          <span class="log-method">${TM.esc(r.method || "")}</span>
          <span class="log-path" title="${TM.esc(path + query)}">${TM.esc(path + query)}</span>
          <span class="log-dur">${r.duration_ms} ms</span>
        </summary>
        <div class="log-more">
          ${r.request_body ? `<div><b>请求体</b><pre>${TM.esc(r.request_body)}</pre></div>` : ""}
          ${r.error ? `<div><b>错误</b><pre class="err">${TM.esc(r.error)}</pre></div>` : ""}
          ${!r.request_body && !r.error ? `<div class="muted">无请求体</div>` : ""}
        </div>
      </details>`;
  }

  function httpRow(r) {
    const url = r.url || "";
    return `
      <details class="log-detail">
        <summary class="log-row log-row-net">
          <span class="log-time">${TM.esc(r.created_at || "")}</span>
          <span class="log-status ${statusClass(r.status)}">${r.status || "ERR"}</span>
          <span class="log-method">${TM.esc(r.method || "")}</span>
          <span class="log-path" title="${TM.esc(url)}">${TM.esc(url)}</span>
          <span class="log-dur">${r.duration_ms} ms</span>
        </summary>
        <div class="log-more">
          ${r.job_id ? `<div class="muted">任务 ${TM.esc(r.job_id)}${r.mailbox_id ? ` · 邮箱 #${r.mailbox_id}` : ""}</div>` : ""}
          ${r.request_body ? `<div><b>请求体</b><pre>${TM.esc(r.request_body)}</pre></div>` : ""}
          ${r.response_body ? `<div><b>响应</b><pre>${TM.esc(r.response_body)}</pre></div>` : ""}
          ${r.error ? `<div><b>错误</b><pre class="err">${TM.esc(r.error)}</pre></div>` : ""}
        </div>
      </details>`;
  }

  function render(rows, forKind) {
    if (!rows || !rows.length) {
      el.list.innerHTML = `<div class="empty">没有记录。</div>`;
      el.count.textContent = "0 条";
      return;
    }
    el.count.textContent = `${rows.length} 条`;
    const map = { business: businessRow, system: businessRow, access: accessRow, http: httpRow };
    el.list.innerHTML = rows.map(map[forKind] || businessRow).join("");
  }

  async function load() {
    // 记住发起请求时的页签，避免慢响应覆盖当前页签
    const requestKind = kind;
    el.list.innerHTML = `<div class="empty">加载中…</div>`;
    const useLevel = requestKind === "business" || requestKind === "system";
    try {
      const rows = await API.getLogs({
        kind: requestKind,
        level: useLevel ? el.level.value : "",
        keyword: el.keyword.value.trim(),
        limit: 200,
      });
      if (requestKind !== kind) return;   // 用户已经切走
      render(rows, requestKind);
    } catch (e) {
      if (requestKind !== kind) return;
      el.list.innerHTML = `<div class="empty">${TM.esc(e.message)}</div>`;
    }
  }

  function switchKind(next) {
    kind = next;
    document.querySelectorAll("#logs-modal .tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.kind === kind);
    });
    const useLevel = kind === "business" || kind === "system";
    el.level.disabled = !useLevel;
    el.level.style.opacity = useLevel ? "1" : ".45";
    el.keyword.placeholder = kind === "access"
      ? "按路径 / 错误搜索"
      : kind === "http" ? "按 URL / 响应内容搜索" : "按内容搜索";
    load();
  }

  async function clearCurrent() {
    const names = { business: "业务", system: "系统", access: "前端请求", http: "外部请求" };
    if (!confirm(`清空${names[kind]}日志？此操作不可恢复。`)) return;
    try {
      const data = await API.clearLogs(kind === "system" ? "business" : kind);
      TM.toast(`已清空 ${data.removed} 条`);
      await load();
    } catch (e) {
      TM.toast(e.message, true);
    }
  }

  function open() {
    el.modal.hidden = false;
    switchKind("business");
  }

  function close() {
    el.modal.hidden = true;
  }

  document.querySelectorAll("#logs-modal .tab").forEach((btn) => {
    btn.onclick = () => switchKind(btn.dataset.kind);
  });
  el.level.onchange = load;
  el.refresh.onclick = load;
  el.keyword.addEventListener("keydown", (e) => {
    if (e.key === "Enter") load();
  });
  el.clear.onclick = clearCurrent;
  el.cancel.onclick = close;
  el.close.onclick = close;
  el.modal.addEventListener("click", (e) => {
    if (e.target === el.modal) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !el.modal.hidden) close();
  });

  const entry = document.getElementById("set-logs");
  if (entry) entry.onclick = open;

  window.TMLogs = { open, close, reload: load };
})();
