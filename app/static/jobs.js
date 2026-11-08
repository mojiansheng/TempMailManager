/* 批量任务面板：抓信 / 续期。
   流程：选择 → 确认 → 进度；另有历史任务列表。
   任务跑在后端，页面重开后通过 /api/jobs/active 自动接上。依赖 window.TM。 */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const el = {
    modal: $("#job-modal"),
    title: $("#job-title"),
    close: $("#job-close"),
    pickCount: $("#job-pick-count"),
    tree: $("#job-tree"),
    hint: $("#job-hint"),
    summary: $("#job-summary"),
    confirmList: $("#job-confirm-list"),
    bar: $("#job-bar"),
    progressText: $("#job-progress-text"),
    results: $("#job-results"),
    history: $("#job-history"),
    back: $("#job-back"),
    cancelBtn: $("#job-cancel-btn"),
    next: $("#job-next"),
    stop: $("#job-stop"),
    historyBtn: $("#job-history-btn"),
    btnFetch: document.getElementById("btn-fetch"),
    btnRenewAll: document.getElementById("btn-renew-all"),
  };

  const st = {
    kind: "fetch",
    mode: "select",          // select | confirm | run | history | detail
    selected: new Set(),
    jobId: null,
    job: null,
    timer: null,             // 面板内进度轮询
    bgTimer: null,           // 面板关闭时只刷按钮文案
    gapText: "",
    settings: null,
  };

  /* ---------------- 数据 ---------------- */
  function eligible() {
    const list = TM.state.mailboxes;
    return st.kind === "renew" ? list.filter((m) => m.auto_renew) : list;
  }

  function eligibleMap() {
    const map = new Map();
    eligible().forEach((m) => map.set(m.id, m));
    return map;
  }

  function mailboxesInGroup(groupId) {
    const ids = TM.subtreeIds(Number(groupId));
    return eligible().filter((m) => m.group_id && ids.has(m.group_id));
  }

  function groupsOf(mb) {
    return mb.group_id ? TM.groupName(mb.group_id) : "未分组";
  }

  function kindName(kind) {
    return kind === "fetch" ? "抓取邮件" : "续期";
  }

  /* ---------------- 渲染：选择树 ---------------- */
  function treeRow({ id, label, depth, kind, count, checked, partial, tag }) {
    const attr = kind === "group" ? `data-gid="${id}"` : `data-mid="${id}"`;
    return `
      <div class="jt-row ${kind}" ${attr} style="padding-left:${10 + depth * 16}px">
        <input type="checkbox" ${checked ? "checked" : ""} ${partial ? 'data-partial="1"' : ""} ${attr}>
        <span class="jt-name" title="${TM.esc(label)}">${TM.esc(label)}</span>
        ${tag ? `<span class="jt-tag">${tag}</span>` : ""}
        <span class="jt-count">${count}</span>
      </div>`;
  }

  function renderTree() {
    const parts = [];
    const roots = TM.childGroups(null);

    const emitGroup = (group, depth) => {
      const mails = mailboxesInGroup(group.id);
      const picked = mails.filter((m) => st.selected.has(m.id)).length;
      if (mails.length) {
        parts.push(treeRow({
          id: group.id, label: group.name, depth, kind: "group",
          count: `${picked}/${mails.length}`,
          checked: picked > 0 && picked === mails.length,
          partial: picked > 0 && picked < mails.length,
        }));
      }
      mails.sort((a, b) => a.email.localeCompare(b.email)).forEach((m) => {
        parts.push(treeRow({
          id: m.id, label: m.email, depth: depth + 1, kind: "mail",
          count: "", checked: st.selected.has(m.id),
          tag: m.auto_renew ? "" : "手动",
        }));
      });
      TM.childGroups(group.id).forEach((child) => emitGroup(child, depth + 1));
    };

    roots.forEach((g) => emitGroup(g, 0));

    const loose = eligible().filter((m) => !m.group_id);
    if (loose.length) {
      const picked = loose.filter((m) => st.selected.has(m.id)).length;
      parts.push(treeRow({
        id: "none", label: "未分组", depth: 0, kind: "group",
        count: `${picked}/${loose.length}`,
        checked: picked > 0 && picked === loose.length,
        partial: picked > 0 && picked < loose.length,
      }));
      loose.sort((a, b) => a.email.localeCompare(b.email)).forEach((m) => {
        parts.push(treeRow({
          id: m.id, label: m.email, depth: 1, kind: "mail",
          count: "", checked: st.selected.has(m.id), tag: m.auto_renew ? "" : "手动",
        }));
      });
    }

    el.tree.innerHTML = parts.join("") || `<div class="empty">没有符合条件的邮箱</div>`;
    el.tree.querySelectorAll('input[data-partial="1"]').forEach((box) => {
      box.indeterminate = true;
    });
    updatePickCount();
  }

  function updatePickCount() {
    el.pickCount.textContent = `已选 ${st.selected.size} / ${eligible().length}`;
  }

  /* ---------------- 渲染：确认 ---------------- */
  function renderConfirm() {
    const map = eligibleMap();
    const picked = [...st.selected].map((id) => map.get(id)).filter(Boolean);
    picked.sort((a, b) => a.email.localeCompare(b.email));

    const gap = st.settings ? st.settings[st.kind] : null;
    let perItem = st.kind === "fetch" ? 500 : 800;
    if (gap) {
      if (gap.gap_mode === "random") {
        perItem = (gap.gap_min_ms + gap.gap_max_ms) / 2;
        st.gapText = `随机 ${gap.gap_min_ms}~${gap.gap_max_ms} ms`;
      } else {
        perItem = gap.gap_ms;
        st.gapText = `固定 ${gap.gap_ms} ms`;
      }
    }
    const estimate = Math.max(0, picked.length) * (perItem + 1200) / 1000;
    el.summary.textContent =
      `将处理 ${picked.length} 个邮箱，请求间隔约 ${st.gapText}，预计 ${Math.ceil(estimate)} 秒。`;

    el.confirmList.innerHTML = picked.map((m) => `
      <div class="job-list-row">
        <span class="job-list-main">${TM.esc(m.email)}</span>
        <span class="job-list-sub">${TM.esc(groupsOf(m))}${m.auto_renew ? "" : " · 手动续期"}</span>
      </div>`).join("");
  }

  /* ---------------- 渲染：进度 ---------------- */
  function renderJob(job) {
    st.job = job;
    const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
    el.bar.style.width = pct + "%";

    if (job.status === "running") {
      el.progressText.textContent =
        `${job.done}/${job.total} · 正在处理 ${job.current || "…"}`;
    } else if (job.status === "interrupted") {
      el.progressText.textContent =
        `任务中断 · 已完成 ${job.done}/${job.total}，成功 ${job.success}，失败 ${job.failed}`;
    } else {
      el.progressText.textContent =
        `${job.status === "cancelled" ? "已终止" : "已完成"} · 成功 ${job.success}，失败 ${job.failed}`;
    }

    const rows = (job.results || []).slice().reverse().map((r) => `
      <div class="job-res-row ${r.ok ? "ok" : "fail"}">
        <span class="job-res-main">${TM.esc(r.email || "—")}</span>
        <span class="job-res-sub">${r.ok
          ? (job.kind === "fetch" ? `新邮件 ${r.new || 0}` : "已续期")
          : TM.esc(r.error || "失败")}</span>
      </div>`).join("");
    el.results.innerHTML = rows || `<div class="empty">还没有结果</div>`;

    if (job.status !== "running") {
      stopPolling();
      if (st.timer) {
        clearInterval(st.timer);
        st.timer = null;
      }
      TM.reload().then(() => {
        if (TM.state.currentId) TM.loadEmails();
      });
    }
    updateFooter();
  }

  async function poll() {
    if (!st.jobId) return;
    try {
      renderJob(await API.getJob(st.jobId));
    } catch (e) {
      if (st.timer) {
        clearInterval(st.timer);
        st.timer = null;
      }
    }
  }

  function startPolling() {
    if (st.timer) clearInterval(st.timer);
    st.timer = setInterval(poll, 700);
  }

  function stopPolling() {
    if (st.timer) {
      clearInterval(st.timer);
      st.timer = null;
    }
  }

  /* ---------------- 底栏 ---------------- */
  function setBtn(btn, text, visible, disabled) {
    btn.textContent = text;
    btn.hidden = !visible;
    btn.disabled = !!disabled;
  }

  function updateFooter() {
    const running = st.job && st.job.status === "running";
    el.back.hidden = true;
    el.back.textContent = "上一步";

    if (st.mode === "select") {
      setBtn(el.next, "下一步", true, st.selected.size === 0);
      setBtn(el.cancelBtn, "取消", true);
      el.stop.hidden = true;
      el.next.onclick = goConfirm;
    } else if (st.mode === "confirm") {
      el.back.hidden = false;
      setBtn(el.next, "开始", true);
      setBtn(el.cancelBtn, "取消", true);
      el.stop.hidden = true;
      el.next.onclick = startJob;
    } else if (st.mode === "history") {
      setBtn(el.next, "完成", false);
      setBtn(el.cancelBtn, "关闭", true);
      el.stop.hidden = true;
    } else {
      // run / detail
      el.back.hidden = st.mode !== "detail";
      if (st.mode === "detail") el.back.textContent = "返回列表";
      el.stop.hidden = !running;
      if (running) setBtn(el.cancelBtn, "后台运行", true);
      else el.cancelBtn.hidden = true;
      setBtn(el.next, "完成", !running);
      el.next.onclick = () => finish();
    }
  }

  /* ---------------- 步骤切换 ---------------- */
  function showStep(mode) {
    st.mode = mode;
    const stepMap = { select: 1, confirm: 2, run: 3, detail: 3, history: 4 };
    const step = stepMap[mode];
    el.modal.querySelectorAll(".job-step").forEach((node) => {
      node.hidden = Number(node.dataset.step) !== step;
    });
    updateFooter();
  }

  function goConfirm() {
    if (!st.selected.size) {
      TM.toast("请先选择邮箱", true);
      return;
    }
    renderConfirm();
    showStep("confirm");
  }

  async function startJob() {
    el.next.disabled = true;
    el.next.classList.add("loading");
    try {
      const job = await API.createJob(st.kind, "ids", [...st.selected]);
      st.jobId = job.id;
      showStep("run");
      renderJob(job);
      startPolling();
      TM.toast("任务已提交到后台，可以关闭页面");
    } catch (e) {
      TM.toast(e.message, true);
    } finally {
      el.next.classList.remove("loading");
      updateFooter();
    }
  }

  function finish() {
    close();
    TM.reload().then(() => {
      if (TM.state.currentId) TM.loadEmails();
    });
  }

  /* ---------------- 历史 ---------------- */
  async function showHistory() {
    el.history.innerHTML = `<div class="empty">加载中…</div>`;
    showStep("history");
    try {
      const list = await API.listJobs();
      if (!list || !list.length) {
        el.history.innerHTML = `<div class="empty">还没有任务记录。</div>`;
        return;
      }
      el.history.innerHTML = list.map((job) => `
        <div class="job-hist-row" data-id="${job.id}">
          <span class="job-hist-kind ${job.kind}">${kindName(job.kind)}</span>
          <span class="job-hist-main">
            ${job.total} 个 · 成功 ${job.success}${job.failed ? ` · 失败 ${job.failed}` : ""}
          </span>
          <span class="job-hist-time">${TM.esc(job.started_at || "")}</span>
          <span class="job-hist-status ${job.status}">${statusText(job.status)}</span>
        </div>`).join("");
    } catch (e) {
      el.history.innerHTML = `<div class="empty">${TM.esc(e.message)}</div>`;
    }
  }

  function statusText(status) {
    return ({
      running: "进行中",
      done: "完成",
      cancelled: "已终止",
      interrupted: "中断",
    })[status] || status;
  }

  async function openDetail(jobId) {
    try {
      const job = await API.getJob(jobId);
      st.jobId = job.id;
      st.job = job;
      el.title.textContent = `${kindName(job.kind)} · 任务详情`;
      showStep("detail");
      renderJob(job);
    } catch (e) {
      TM.toast(e.message, true);
    }
  }

  /* ---------------- 恢复后台任务 ---------------- */
  function syncBadge(job) {
    if (!el.btnFetch) return;
    if (job && job.status === "running") {
      el.btnFetch.textContent = `抓取邮件 ${job.done}/${job.total}`;
      el.btnFetch.classList.add("running");
    } else {
      el.btnFetch.textContent = "抓取邮件";
      el.btnFetch.classList.remove("running");
    }
  }

  function startBgWatch() {
    if (st.bgTimer) return;
    st.bgTimer = setInterval(async () => {
      try {
        const job = await API.activeJob();
        syncBadge(job);
        if (!job) {
          clearInterval(st.bgTimer);
          st.bgTimer = null;
          TM.reload().then(() => {
            if (TM.state.currentId) TM.loadEmails();
          });
          TM.toast("后台任务已完成");
        }
      } catch (e) {
        clearInterval(st.bgTimer);
        st.bgTimer = null;
      }
    }, 2500);
  }

  async function resume() {
    let job = null;
    try {
      job = await API.activeJob();
    } catch (e) {
      return;
    }
    syncBadge(job);
    if (!job) return;

    st.kind = job.kind;
    st.jobId = job.id;
    st.job = job;
    openShell(job.kind);
    el.title.textContent = `${kindName(job.kind)} · 进行中`;
    showStep("run");
    renderJob(job);
    startPolling();
    TM.toast("已接上正在运行的后台任务");
  }

  /* ---------------- 打开 / 关闭 ---------------- */
  function openShell(kind) {
    st.kind = kind;
    el.title.textContent = kindName(kind);
    el.hint.textContent = kind === "fetch"
      ? "勾选要抓取的邮箱（可整组勾选）。任务提交到后台，关闭页面也会继续执行。"
      : "只列出已勾选「自动续期」的邮箱；续期会把有效期重新设为设置里的天数。";
    el.results.innerHTML = "";
    el.bar.style.width = "0%";
    el.progressText.textContent = "准备中…";
    el.modal.hidden = false;
  }

  async function open(kind = "fetch") {
    st.selected = new Set();
    st.jobId = null;
    st.job = null;
    openShell(kind);
    try {
      const data = await API.getSettings();
      st.settings = data.settings;
    } catch (e) {
      st.settings = null;
    }
    renderTree();
    showStep("select");
  }

  function close() {
    stopPolling();
    el.modal.hidden = true;
    if (st.job && st.job.status === "running") {
      startBgWatch();
      TM.toast("任务在后台继续运行，可随时打开查看");
    }
  }

  /* ---------------- 事件 ---------------- */
  el.tree.addEventListener("click", (event) => {
    const row = event.target.closest(".jt-row");
    if (!row) return;
    const isBox = event.target.tagName === "INPUT";

    if (row.dataset.mid) {
      const id = Number(row.dataset.mid);
      const want = isBox ? event.target.checked : !st.selected.has(id);
      want ? st.selected.add(id) : st.selected.delete(id);
      renderTree();
      updateFooter();
      return;
    }

    if (row.dataset.gid) {
      const gid = row.dataset.gid;
      const list = gid === "none"
        ? eligible().filter((m) => !m.group_id)
        : mailboxesInGroup(gid);
      const allPicked = list.length > 0 && list.every((m) => st.selected.has(m.id));
      const want = isBox ? event.target.checked : !allPicked;
      list.forEach((m) => (want ? st.selected.add(m.id) : st.selected.delete(m.id)));
      renderTree();
      updateFooter();
    }
  });

  function pickAll(mode) {
    const all = eligible();
    if (mode === "all") st.selected = new Set(all.map((m) => m.id));
    else if (mode === "none") st.selected = new Set();
    else st.selected = new Set(all.filter((m) => !st.selected.has(m.id)).map((m) => m.id));
    renderTree();
    updateFooter();
  }

  $("#job-select-all").onclick = () => pickAll("all");
  $("#job-select-none").onclick = () => pickAll("none");
  $("#job-select-invert").onclick = () => pickAll("invert");
  if (el.historyBtn) el.historyBtn.onclick = showHistory;

  el.history.addEventListener("click", (event) => {
    const row = event.target.closest(".job-hist-row");
    if (row) openDetail(row.dataset.id);
  });

  el.back.onclick = () => {
    if (st.mode === "detail") showHistory();
    else showStep("select");
  };

  el.cancelBtn.onclick = () => {
    if (st.mode === "run" && st.job && st.job.status === "running") {
      close();   // 后台继续跑
      return;
    }
    close();
  };

  el.stop.onclick = async () => {
    if (!st.jobId) return;
    try {
      await API.cancelJob(st.jobId);
      TM.toast("已请求终止，当前这一封跑完就停");
    } catch (e) {
      TM.toast(e.message, true);
    }
  };

  el.close.onclick = () => close();
  el.modal.addEventListener("click", (e) => {
    if (e.target === el.modal) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !el.modal.hidden) close();
  });

  if (el.btnFetch) el.btnFetch.onclick = () => open("fetch");
  if (el.btnRenewAll) el.btnRenewAll.onclick = () => open("renew");

  window.TMJobs = { open, close, resume };
})();
