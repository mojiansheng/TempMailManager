/* 前端核心：状态 / 渲染 / 动作。分组在 groups.js，导入在 importer.js。 */
(() => {
  const state = {
    mailboxes: [],
    groups: [],
    selectedGroup: "all", // "all" | "ungrouped" | 分组 id
    expanded: new Set(),
    currentId: null,
    emails: [],
    currentEmailId: null,
    detail: null,
    timer: null,
    noteId: null,
    selectMode: false,
    selected: new Set(),
    privacy: false,        // 隐私显示：邮箱地址中间打码
    noteOpen: new Set(),   // 展开了备注的邮箱 id
  };

  const $ = (sel) => document.querySelector(sel);
  const el = {
    list: $("#mailbox-list"),
    count: $("#mailbox-count"),
    scope: $("#list-scope"),
    btnCreate: $("#btn-create"),
    btnImport: $("#btn-import"),
    btnPrivacy: $("#btn-privacy"),
    chkAutoRenew: $("#create-auto-renew"),
    createLifetime: $("#create-lifetime"),
    currentEmail: $("#current-email"),
    currentMeta: $("#current-meta"),
    btnRefresh: $("#btn-refresh"),
    btnRenew: $("#btn-renew"),
    groupSelect: $("#mb-group"),
    mailList: $("#mail-list"),
    detail: $("#mail-detail"),
    toast: $("#toast"),
    modal: $("#modal"),
    modalSubject: $("#modal-subject"),
    modalMeta: $("#modal-meta"),
    modalFrame: $("#modal-frame"),
    noteModal: $("#note-modal"),
    noteTarget: $("#note-target"),
    noteInput: $("#note-input"),
    noteCount: $("#note-count"),
    noteSave: $("#note-save"),
    noteCancel: $("#note-cancel"),
    noteClose: $("#note-close"),
    groupTree: $("#group-tree"),
    btnManage: $("#btn-manage"),
    bulkBar: $("#bulk-bar"),
    bulkCount: $("#bulk-count"),
    bulkMove: $("#bulk-move"),
    bulkAll: $("#bulk-all"),
    bulkExit: $("#bulk-exit"),
  };

  /* ---------------- 工具 ---------------- */
  // 隐私显示：邮箱地址只留前 5 位和后 5 位，中间用 … 代替
  function maskEmail(email) {
    const s = String(email || "");
    if (s.length <= 10) return s;
    return `${s.slice(0, 5)}…${s.slice(-5)}`;
  }

  function displayEmail(email) {
    return state.privacy ? maskEmail(email) : String(email || "");
  }

  // 有效期档位与中文名（与后端 config.py 保持一致；/api/health 可覆盖）
  const LIFETIME_OPTIONS = ["10m", "30m", "1h", "3h", "6h", "24h", "3d", "7d", "15d", "30d"];
  const LIFETIME_LABELS = {
    "10m": "10 分钟", "30m": "30 分钟", "1h": "1 小时", "3h": "3 小时",
    "6h": "6 小时", "24h": "24 小时", "3d": "3 天", "7d": "7 天",
    "15d": "15 天", "30d": "30 天",
  };

  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));

  function toast(message, isError = false) {
    el.toast.textContent = message;
    el.toast.className = "toast show" + (isError ? " error" : "");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.toast.className = "toast"; }, 2600);
  }

  function parseTime(value) {
    if (!value) return null;
    const d = new Date(String(value).replace(" ", "T"));
    return isNaN(d.getTime()) ? null : d;
  }

  function relTime(value) {
    const d = parseTime(value);
    if (!d) return "—";
    const diff = Date.now() - d.getTime();
    if (diff < 60e3) return "刚刚";
    if (diff < 3600e3) return `${Math.floor(diff / 60e3)} 分钟前`;
    if (diff < 86400e3) return `${Math.floor(diff / 3600e3)} 小时前`;
    return `${Math.floor(diff / 86400e3)} 天前`;
  }

  // 有效期标记 → 总天数（用于倒计时）
  // 小时级有效期剩余（分钟/小时档）：返回剩余分钟数，不足 1 天时用
  function minutesLeft(mailbox) {
    const base = parseTime(mailbox.last_renewed_at || mailbox.created_at);
    if (!base) return null;
    const totalMin = { "10m": 10, "30m": 30, "1h": 60, "3h": 180, "6h": 360 }[String(mailbox.lifetime || "")];
    if (totalMin == null) return null;
    return Math.max(0, totalMin - Math.floor((Date.now() - base.getTime()) / 60e3));
  }

  function lifetimeDays(lifetime) {
    const map = { "10m": 0, "30m": 0, "1h": 0, "3h": 0, "6h": 0, "24h": 1,
                  "3d": 3, "7d": 7, "15d": 15, "30d": 30 };
    return map[String(lifetime || "30d")] ?? 30;
  }

  function daysLeft(mailbox) {
    const base = parseTime(mailbox.last_renewed_at || mailbox.created_at);
    if (!base) return null;
    const total = lifetimeDays(mailbox.lifetime);
    const left = total - Math.floor((Date.now() - base.getTime()) / 86400e3);
    return Math.max(0, left);
  }

  function withBusy(btn, fn) {
    return async (...args) => {
      if (btn.classList.contains("loading")) return;
      btn.classList.add("loading");
      btn.disabled = true;
      try {
        await fn(...args);
      } catch (e) {
        toast(e.message || "操作失败", true);
      } finally {
        btn.classList.remove("loading");
        btn.disabled = false;
      }
    };
  }

  /* ---------------- 分组辅助 ---------------- */
  function groupName(id) {
    const g = state.groups.find((x) => x.id === id);
    return g ? g.name : "";
  }

  function childGroups(parentId) {
    return state.groups.filter((g) => (g.parent_id || null) === (parentId || null));
  }

  function subtreeIds(groupId) {
    const out = new Set([groupId]);
    const walk = (pid) => {
      childGroups(pid).forEach((g) => {
        out.add(g.id);
        walk(g.id);
      });
    };
    walk(groupId);
    return out;
  }

  function visibleMailboxes() {
    const sel = state.selectedGroup;
    if (sel === "all") return state.mailboxes;
    if (sel === "ungrouped") return state.mailboxes.filter((m) => !m.group_id);
    const ids = subtreeIds(Number(sel));
    return state.mailboxes.filter((m) => m.group_id && ids.has(m.group_id));
  }

  function countInScope() {
    return visibleMailboxes().length;
  }

  /* ---------------- 渲染：邮箱列表 ---------------- */
  function renderMailboxes() {
    const list = visibleMailboxes();
    el.count.textContent = list.length;
    if (el.scope) {
      el.scope.textContent =
        state.selectedGroup === "all" ? "全部"
          : state.selectedGroup === "ungrouped" ? "未分组"
            : groupName(Number(state.selectedGroup)) || "分组";
    }
    if (!list.length) {
      const hint = state.mailboxes.length
        ? "这个分组下还没有邮箱，可从「未分组」里移动过来。"
        : "还没有邮箱，点击右上角「新建」或「导入」。";
      el.list.innerHTML = `<div class="empty">${hint}</div>`;
      return;
    }
    el.list.innerHTML = list.map((mb) => {
      const left = daysLeft(mb);
      const gname = mb.group_id ? groupName(mb.group_id) : "";
      const renewTag = mb.auto_renew
        ? `<span class="tag on">自动续期</span>`
        : `<span class="tag off">手动</span>`;
      const unread = mb.unread_count
        ? `<span class="tag unread">${mb.unread_count} 未读</span>` : "";
      const groupTag = gname ? `<span class="tag group">${esc(gname)}</span>` : "";
      return `
        <div class="mb-card ${mb.id === state.currentId ? "active" : ""} ${state.selectMode ? "manage" : ""} ${state.selected.has(mb.id) ? "selected" : ""}"
             data-id="${mb.id}">
          <div class="mb-top">
            ${state.selectMode
              ? `<input type="checkbox" class="mb-check" ${state.selected.has(mb.id) ? "checked" : ""} tabindex="-1">`
              : ""}
            <div class="mb-email" title="${esc(mb.email)}">${esc(displayEmail(mb.email))}</div>
            <span class="type-badge" title="邮箱类型">T${mb.type || 1}</span>
          </div>
          <div class="mb-sub">
            ${renewTag}
            <span class="tag">${esc(mb.lifetime || "30d")}</span>
            <span>${(() => { const m = minutesLeft(mb); return m != null ? (m >= 60 ? `剩余约 ${Math.floor(m / 60)} 小时` : `剩余约 ${m} 分钟`) : (left == null ? "—" : `剩余约 ${left} 天`); })()}</span>
            ${unread}
            ${groupTag}
          </div>
          <div class="mb-sub">
            <span>创建于 ${relTime(mb.created_at)}</span>
            <span>· ${mb.email_count || 0} 封邮件</span>
          </div>
          ${mb.note
            ? `<div class="mb-note ${state.noteOpen.has(mb.id) ? "" : "collapsed"}"
                   data-note-id="${mb.id}" title="${state.noteOpen.has(mb.id) ? esc(mb.note) : "点击展开备注"}">
                 ${state.noteOpen.has(mb.id) ? esc(mb.note) : `<span class="note-preview">📝 备注（点击查看）</span>`}
               </div>`
            : ""}
          ${mb.last_error ? `<div class="mb-sub" style="color:#e5484d">${esc(mb.last_error)}</div>` : ""}
          <div class="mb-actions">
            <button class="mini" data-act="copy" title="复制邮箱地址">复制</button>
            <button class="mini" data-act="renew" title="立即续期（可选择时长）">续期</button>
            <button class="mini ${mb.auto_renew ? "on" : ""}" data-act="auto"
                    title="${mb.auto_renew ? "点击关闭每日自动续期" : "点击开启每日自动续期"}">
              自动续期${mb.auto_renew ? "开" : "关"}
            </button>
            <button class="mini" data-act="note" title="${mb.note ? "修改备注" : "添加备注"}">
              ${mb.note ? "改备注" : "备注"}
            </button>
            <button class="mini danger" data-act="delete" title="删除邮箱">删除</button>
          </div>
        </div>`;
    }).join("");
    bindMailboxDrag();
  }

  /* ---------------- 邮箱卡片拖动排序（当前可见列表内） ---------------- */
  let dragMailId = null;

  function bindMailboxDrag() {
    el.list.querySelectorAll(".mb-card").forEach((card) => {
      card.draggable = !state.selectMode;
      if (state.selectMode) return;

      card.ondragstart = (e) => {
        dragMailId = Number(card.dataset.id);
        // 拖到左侧分组可批量移入：拖已勾选的卡片时带上全部勾选项
        const ids = state.selected.has(dragMailId) ? [...state.selected] : [dragMailId];
        window.TM.draggingMailboxIds = ids;
        card.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        try {
          e.dataTransfer.setData("text/plain", String(dragMailId));
          e.dataTransfer.setData("application/x-tm-mailbox", String(ids.length));
        } catch (_) {}
      };
      card.ondragend = () => {
        card.classList.remove("dragging");
        el.list.querySelectorAll(".drop-target").forEach((n) => n.classList.remove("drop-target"));
        dragMailId = null;
        window.TM.draggingMailboxIds = null;
      };
      card.ondragover = (e) => {
        if (dragMailId == null || Number(card.dataset.id) === dragMailId) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        card.classList.add("drop-target");
      };
      card.ondragleave = () => card.classList.remove("drop-target");
      card.ondrop = async (e) => {
        e.preventDefault();
        card.classList.remove("drop-target");
        if (dragMailId == null || Number(card.dataset.id) === dragMailId) return;

        // 全局顺序重排：以当前可见列表顺序为基准，把拖动的插到目标前
        const visibleIds = visibleMailboxes().map((m) => m.id);
        const from = visibleIds.indexOf(dragMailId);
        const to = visibleIds.indexOf(Number(card.dataset.id));
        if (from < 0 || to < 0) return;
        visibleIds.splice(to, 0, visibleIds.splice(from, 1)[0]);

        // 没动的其它邮箱保持原相对顺序：合并 visible 与其余
        const rest = state.mailboxes.map((m) => m.id).filter((id) => !visibleIds.includes(id));
        try {
          await API.reorderMailboxes([...visibleIds, ...rest]);
          await loadMailboxes();
          toast("邮箱顺序已保存");
        } catch (err) {
          toast(err.message, true);
        }
      };
    });
  }

  function currentMailbox() {
    return state.mailboxes.find((m) => m.id === state.currentId) || null;
  }

  function renderHeader() {
    const mb = currentMailbox();
    const has = !!mb;
    el.btnRefresh.disabled = !has;
    el.btnRenew.disabled = !has;
    el.groupSelect.disabled = !has;
    if (!mb) {
      el.currentEmail.textContent = "未选择邮箱";
      el.currentMeta.innerHTML = "";
      el.groupSelect.innerHTML = `<option>—</option>`;
      return;
    }
    el.currentEmail.textContent = displayEmail(mb.email);
    el.currentEmail.title = mb.email;
    el.currentMeta.innerHTML = `
      <span>有效期 ${esc(mb.lifetime || "30d")}</span>
      <span>· ${(() => { const m = minutesLeft(mb); return m != null ? (m >= 60 ? `剩余约 ${Math.floor(m / 60)} 小时` : `剩余约 ${m} 分钟`) : `剩余约 ${daysLeft(mb) ?? "—"} 天`; })()}</span>
      <span>· ${mb.auto_renew ? "每日自动续期" : "未开启自动续期"}</span>
      <span>· 上次收信 ${relTime(mb.last_checked_at)}</span>`;

    const options = [`<option value="">未分组</option>`];
    const walk = (parentId, depth) => {
      childGroups(parentId).forEach((g) => {
        const pad = "　".repeat(depth);
        options.push(
          `<option value="${g.id}" ${mb.group_id === g.id ? "selected" : ""}>${pad}${esc(g.name)}</option>`
        );
        walk(g.id, depth + 1);
      });
    };
    walk(null, 0);
    el.groupSelect.innerHTML = options.join("");
  }

  /* ---------------- 批量管理：勾选邮箱后一起移入分组 ---------------- */
  function setSelectMode(on) {
    state.selectMode = on;
    state.selected.clear();
    el.btnManage.classList.toggle("on", on);
    el.btnManage.title = on ? "退出批量管理" : "批量管理：勾选多个邮箱后一起移入分组";
    el.bulkBar.hidden = !on;
    renderMailboxes();
    updateBulkBar();
  }

  function toggleSelect(id) {
    if (state.selected.has(id)) state.selected.delete(id);
    else state.selected.add(id);
    renderMailboxes();
    updateBulkBar();
  }

  function updateBulkBar() {
    el.bulkCount.textContent = `已选 ${state.selected.size} 个`;
    el.bulkMove.disabled = !state.selected.size;
  }

  /* 分组下拉选项（带层级缩进），value 空串代表未分组 */
  function groupSelectOptions() {
    const out = [{ value: "", label: "未分组（不放入任何分组）" }];
    const walk = (parentId, depth) => {
      childGroups(parentId).forEach((g) => {
        out.push({ value: String(g.id), label: `${"　".repeat(depth)}${depth ? "└ " : ""}${g.name}` });
        walk(g.id, depth + 1);
      });
    };
    walk(null, 0);
    return out;
  }

  async function bulkMoveMailboxes() {
    const ids = [...state.selected];
    if (!ids.length) {
      toast("请先勾选要移动的邮箱", true);
      return;
    }
    const pick = await TMDialog.select({
      title: "移入分组",
      label: `已选 ${ids.length} 个邮箱，选择要放入的分组：`,
      options: groupSelectOptions(),
      confirmText: "移动",
    });
    if (pick == null) return;
    const groupId = pick === "" ? null : Number(pick);
    try {
      const res = await API.moveMailboxes(ids, groupId);
      toast(`已移动 ${res.moved} 个邮箱到「${groupId ? groupName(groupId) : "未分组"}」`);
      setSelectMode(false);
      await reload();
    } catch (e) {
      toast(e.message, true);
    }
  }

  el.btnManage.onclick = () => setSelectMode(!state.selectMode);
  el.bulkMove.onclick = bulkMoveMailboxes;
  el.bulkAll.onclick = () => {
    visibleMailboxes().forEach((m) => state.selected.add(m.id));
    renderMailboxes();
    updateBulkBar();
  };
  el.bulkExit.onclick = () => setSelectMode(false);

  /* ---------------- 渲染：邮件列表 ---------------- */
  function renderEmails() {
    const mb = currentMailbox();
    if (!mb) {
      el.mailList.innerHTML = `<div class="empty big">选择左侧的一个邮箱，查看它收到的邮件。</div>`;
      return;
    }
    if (!state.emails.length) {
      el.mailList.innerHTML = `<div class="empty big">这个邮箱还没有收到邮件。<br>把地址复制去注册后，点「刷新邮件」。</div>`;
      return;
    }
    el.mailList.innerHTML = state.emails.map((m) => `
      <div class="mail-item ${m.is_read ? "" : "unread"} ${m.id === state.currentEmailId ? "active" : ""}"
           data-id="${m.id}">
        <div class="from">${esc(m.sender || "未知发件人")}</div>
        <div class="subject">${esc(m.subject || "(无主题)")}</div>
        <div class="date">${esc(m.received_at || relTime(m.fetched_at))}</div>
      </div>`).join("");
  }

  /* ---------------- 渲染：邮件详情 ---------------- */
  function safeEmailDocument(email) {
    const body = email.body_html && email.body_html.trim()
      ? email.body_html
      : `<pre style="white-space:pre-wrap;">${esc(email.body_text || "(空内容)")}</pre>`;
    return `<!DOCTYPE html><html><head><meta charset="utf-8">
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src https: http: data:; base-uri 'none'; form-action 'none';">
      <style>body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
      line-height:1.65;color:#333;background:#fff;margin:16px;overflow-wrap:anywhere;}
      img{max-width:100%;height:auto}</style></head><body>${body}</body></html>`;
  }

  function renderDetail() {
    const email = state.detail;
    if (!email) {
      el.detail.innerHTML = `<div class="empty big">点击一封邮件查看内容。</div>`;
      return;
    }
    el.detail.innerHTML = `
      <div class="detail-head">
        <h3>${esc(email.subject || "(无主题)")}</h3>
        <div class="line">发件人：${esc(email.sender || "未知")}</div>
        <div class="line">时间：${esc(email.received_at || "")}</div>
        <div class="line" style="margin-top:8px">
          <button class="mini" id="btn-expand">放大查看</button>
          <button class="mini danger" id="btn-delete-mail">删除此邮件</button>
        </div>
      </div>
      <div class="detail-body"><iframe id="detail-frame" sandbox="allow-popups allow-popups-to-escape-sandbox"
        referrerpolicy="no-referrer" srcdoc="${esc(safeEmailDocument(email))}"></iframe></div>`;
    $("#btn-expand").onclick = () => openModal(email);
    $("#btn-delete-mail").onclick = () => deleteEmail(email.id);
  }

  function openModal(email) {
    el.modalSubject.textContent = email.subject || "(无主题)";
    el.modalMeta.textContent = `${email.sender || ""} · ${email.received_at || ""}`;

    // 每次放大都重建 iframe。复用同一个节点时，重复赋同样的 srcdoc
    // 浏览器可能不会重新导航；若弹窗隐藏期间文档被回收，就会出现"白板"。
    const fresh = document.createElement("iframe");
    fresh.id = "modal-frame";
    fresh.setAttribute("sandbox", "allow-popups allow-popups-to-escape-sandbox");
    fresh.setAttribute("referrerpolicy", "no-referrer");
    el.modalFrame.replaceWith(fresh);
    el.modalFrame = fresh;

    el.modal.hidden = false;                 // 先显示，保证 iframe 有布局
    fresh.srcdoc = safeEmailDocument(email); // 再写入文档，必定触发一次全新导航
  }

  function closeModal() {
    el.modal.hidden = true;
    // 释放旧文档，避免隐藏的 iframe 占着内存
    if (el.modalFrame) el.modalFrame.removeAttribute("srcdoc");
  }

  /* ---------------- 备注 ---------------- */
  function openNoteDialog(mailboxId) {
    const mb = state.mailboxes.find((m) => m.id === mailboxId);
    if (!mb) return;
    state.noteId = mailboxId;
    el.noteTarget.textContent = displayEmail(mb.email);
    el.noteInput.value = mb.note || "";
    updateNoteCount();
    el.noteModal.hidden = false;
    el.noteInput.focus();
    el.noteInput.setSelectionRange(el.noteInput.value.length, el.noteInput.value.length);
  }

  function closeNoteDialog() {
    el.noteModal.hidden = true;
    state.noteId = null;
  }

  function updateNoteCount() {
    el.noteCount.textContent = el.noteInput.value.length;
  }

  async function saveNote() {
    if (state.noteId == null) return;
    const target = state.noteId;
    el.noteSave.disabled = true;
    try {
      await API.updateMailbox(target, { note: el.noteInput.value.trim() });
      closeNoteDialog();
      await loadMailboxes();
      toast("备注已保存");
    } catch (e) {
      toast(e.message, true);
    } finally {
      el.noteSave.disabled = false;
    }
  }

  el.noteInput.addEventListener("input", updateNoteCount);
  el.noteInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      saveNote();
    }
  });
  el.noteSave.onclick = saveNote;
  el.noteCancel.onclick = closeNoteDialog;
  el.noteClose.onclick = closeNoteDialog;
  el.noteModal.addEventListener("click", (e) => {
    if (e.target === el.noteModal) closeNoteDialog();
  });

  /* ---------------- 数据加载 ---------------- */
  async function loadMailboxes() {
    state.mailboxes = (await API.listMailboxes()) || [];
    const visible = visibleMailboxes();
    // 当前选中的邮箱若被筛选掉（如移动到别的分组）或已删除，清空右侧内容
    if (state.currentId && !visible.some((m) => m.id === state.currentId)) {
      state.currentId = null;
      state.currentEmailId = null;
      state.emails = [];
      state.detail = null;
      renderEmails();
      renderDetail();
    }
    renderMailboxes();
    renderHeader();
    // 分组计数依赖邮箱列表，必须在邮箱加载完后重画一次
    if (typeof TMGroups !== "undefined") TMGroups.render();
  }

  async function loadGroups() {
    state.groups = (await API.listGroups()) || [];
    if (typeof TMGroups !== "undefined") TMGroups.render();
    else renderGroupsFallback();
  }

  function renderGroupsFallback() {
    el.groupTree.innerHTML = `<div class="empty">分组加载失败</div>`;
  }

  async function reload() {
    await loadGroups();
    await loadMailboxes();
  }

  // 选中邮箱只读本地缓存，不再自动请求站点（抓信交给批量任务）
  async function selectMailbox(id) {
    state.currentId = id;
    state.currentEmailId = null;
    state.detail = null;
    renderMailboxes();
    renderHeader();
    renderDetail();
    await loadEmails();
  }

  async function loadEmails() {
    if (!state.currentId) return;
    state.emails = (await API.listEmails(state.currentId)) || [];
    renderEmails();
  }

  async function openEmail(emailId) {
    state.currentEmailId = emailId;
    // 请求前先看本地列表里是不是未读：接口读信时已把它置为已读，
    // 返回体里的 is_read 恒为真，不能用来判断「刚才是未读」。
    const wasUnread = state.emails.some((m) => m.id === emailId && !m.is_read);
    renderEmails();
    const email = await API.getEmail(emailId);
    state.detail = email;
    renderDetail();
    if (wasUnread) {
      // 同步邮件列表与邮箱卡片的未读数，否则要刷新页面才消失
      await loadEmails();
      syncUnreadBadge(email.mailbox_id);
    }
  }

  /* 已读一封后，把邮箱卡片的未读数减一（服务端为准，刷新时再校正） */
  function syncUnreadBadge(mailboxId) {
    const mb = state.mailboxes.find((m) => m.id === mailboxId);
    if (!mb || !mb.unread_count) return;
    mb.unread_count = Math.max(0, mb.unread_count - 1);
    renderMailboxes();
    if (typeof TMGroups !== "undefined") TMGroups.render();
  }

  /* ---------------- 动作 ---------------- */
  el.btnCreate.onclick = withBusy(el.btnCreate, async () => {
    const autoRenew = el.chkAutoRenew.checked;
    el.btnCreate.querySelector(".btn-label").textContent = "创建中…";
    const groupId = state.selectedGroup !== "all" && state.selectedGroup !== "ungrouped"
      ? Number(state.selectedGroup) : null;
    const lifetime = el.createLifetime ? el.createLifetime.value : null;
    try {
      const mb = await API.createMailbox(autoRenew, groupId, lifetime);
      rememberLifetime(lifetime);
      toast(`已创建 ${mb.email}`);
      await reload();
      await selectMailbox(mb.id, { silent: true });
    } finally {
      el.btnCreate.querySelector(".btn-label").textContent = "新建";
    }
  });

  /* 新建邮箱的有效期：记住上次选择，下次打开仍是这个值 */
  const LIFETIME_KEY = "tm.createLifetime";

  function rememberLifetime(value) {
    if (!value) return;
    try { localStorage.setItem(LIFETIME_KEY, value); } catch (_) {}
  }

  function restoreLifetime() {
    if (!el.createLifetime) return;
    let saved = null;
    try { saved = localStorage.getItem(LIFETIME_KEY); } catch (_) {}
    if (saved && [...el.createLifetime.options].some((o) => o.value === saved)) {
      el.createLifetime.value = saved;
    }
    el.createLifetime.onchange = () => rememberLifetime(el.createLifetime.value);
  }

  /* 隐私显示开关：打码邮箱地址，选择记在 localStorage */
  const PRIVACY_KEY = "tm.privacy";

  function applyPrivacyState() {
    // 文案不变、只切高亮，避免按钮宽度变化引起整排按钮跳动
    el.btnPrivacy.classList.toggle("active", state.privacy);
    el.btnPrivacy.textContent = "隐私显示";
    el.btnPrivacy.title = state.privacy
      ? "已开启：邮箱地址只显示前 5 位和后 5 位，点击关闭"
      : "开启后邮箱地址只显示前 5 位和后 5 位，中间打码";
  }

  function restorePrivacy() {
    try { state.privacy = localStorage.getItem(PRIVACY_KEY) === "1"; } catch (_) {}
    applyPrivacyState();
  }

  el.btnPrivacy.onclick = () => {
    state.privacy = !state.privacy;
    try { localStorage.setItem(PRIVACY_KEY, state.privacy ? "1" : "0"); } catch (_) {}
    applyPrivacyState();
    renderMailboxes();
    renderHeader();
    renderGroupsSafe();
    toast(state.privacy ? "已开启隐私显示" : "已关闭隐私显示");
  };

  function renderGroupsSafe() {
    if (typeof TMGroups !== "undefined") TMGroups.render();
  }

  el.btnRefresh.onclick = withBusy(el.btnRefresh, async () => {
    const mb = currentMailbox();
    if (!mb) return;
    const stats = await API.refreshMailbox(mb.id);
    await loadMailboxes();
    await loadEmails();
    toast(stats.new > 0 ? `收到 ${stats.new} 封新邮件` : "已是最新");
  });

  el.btnRenew.onclick = withBusy(el.btnRenew, async () => {
    const mb = currentMailbox();
    if (!mb) return;
    await renewMailboxWithChoice(mb);
  });

  /* 立即续期：弹窗选要续到的时长，默认「保持当前有效期」 */
  async function renewMailboxWithChoice(mb) {
    const options = [
      { value: "", label: `保持当前有效期（${LIFETIME_LABELS[mb.lifetime] || mb.lifetime || "30 天"}）` },
      ...LIFETIME_OPTIONS.map((v) => ({ value: v, label: LIFETIME_LABELS[v] || v })),
    ];
    const pick = await TMDialog.select({
      title: "立即续期",
      label: `${mb.email}\n选择续期后的有效期：`,
      options,
      confirmText: "续期",
    });
    if (pick == null) return;
    const lifetime = pick === "" ? null : pick; // null = 后端沿用当前有效期
    await API.renewMailbox(mb.id, lifetime);
    await loadMailboxes();
    const label = LIFETIME_LABELS[pick] || (lifetime ? lifetime : LIFETIME_LABELS[mb.lifetime] || mb.lifetime);
    toast(`已续期（${label}）`);
  }

  el.groupSelect.onchange = async () => {
    const mb = currentMailbox();
    if (!mb) return;
    const value = el.groupSelect.value;
    try {
      await API.updateMailbox(mb.id, { group_id: value ? Number(value) : null });
      await reload();
      toast(value ? "已移动到分组" : "已移出分组");
    } catch (e) {
      toast(e.message, true);
    }
  };

  el.list.addEventListener("click", async (event) => {
    const card = event.target.closest(".mb-card");
    if (!card) return;
    const id = Number(card.dataset.id);
    const actionBtn = event.target.closest("[data-act]");

    // 批量管理模式：点卡片即勾选/取消，不打开邮箱
    if (state.selectMode) {
      toggleSelect(id);
      return;
    }

    // 点备注条：展开/收起（不触发打开邮箱）
    const noteEl = event.target.closest(".mb-note");
    if (noteEl) {
      const nid = Number(noteEl.dataset.noteId);
      if (state.noteOpen.has(nid)) state.noteOpen.delete(nid);
      else state.noteOpen.add(nid);
      renderMailboxes();
      return;
    }

    if (!actionBtn) {
      await selectMailbox(id);
      return;
    }

    const mb = state.mailboxes.find((m) => m.id === id);
    if (!mb) return;
    const act = actionBtn.dataset.act;

    try {
      if (act === "copy") {
        await navigator.clipboard.writeText(mb.email);
        toast("邮箱地址已复制");
      } else if (act === "renew") {
        actionBtn.disabled = true;
        try {
          await renewMailboxWithChoice(mb);
        } finally {
          actionBtn.disabled = false;
        }
      } else if (act === "auto") {
        await API.updateMailbox(id, { auto_renew: !mb.auto_renew });
        await loadMailboxes();
        toast(!mb.auto_renew ? "已开启每日自动续期" : "已关闭自动续期");
      } else if (act === "note") {
        openNoteDialog(id);
      } else if (act === "delete") {
        const okDel = await TMDialog.confirm({
          title: "删除邮箱",
          message: `确定删除 ${mb.email} ？\n站点上的邮箱与邮件都会被删除，不可恢复。`,
          confirmText: "删除",
          danger: true,
        });
        if (!okDel) return;
        await API.deleteMailbox(id, true);
        if (state.currentId === id) {
          state.currentId = null;
          state.emails = [];
          state.detail = null;
          renderHeader(); renderEmails(); renderDetail();
        }
        await reload();
        toast("已删除");
      }
    } catch (e) {
      toast(e.message, true);
      await loadMailboxes();
    }
  });

  el.mailList.addEventListener("click", async (event) => {
    const item = event.target.closest(".mail-item");
    if (!item) return;
    try {
      await openEmail(Number(item.dataset.id));
    } catch (e) {
      toast(e.message, true);
    }
  });

  async function deleteEmail(emailId) {
    const ok = await TMDialog.confirm({
      title: "删除邮件",
      message: "删除这封邮件？（仅删除本地缓存）",
      confirmText: "删除",
      danger: true,
    });
    if (!ok) return;
    await API.deleteEmail(emailId);
    state.currentEmailId = null;
    state.detail = null;
    await loadEmails();
    renderDetail();
    await loadMailboxes();
    toast("已删除");
  }

  $("#modal-close").onclick = closeModal;
  el.modal.addEventListener("click", (e) => {
    if (e.target === el.modal) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    closeModal();
    if (!el.noteModal.hidden) closeNoteDialog();
  });

  /* ---------------- 对外暴露 ---------------- */
  window.TM = {
    state, el, esc, toast, relTime, daysLeft, withBusy,
    loadMailboxes, loadGroups, reload, selectMailbox, loadEmails,
    renderMailboxes, renderHeader, renderEmails, renderDetail,
    currentMailbox, visibleMailboxes, countInScope,
    groupName, childGroups, subtreeIds, openNoteDialog,
  };

  /* ---------------- 启动 ---------------- */
  function bindNoticeBar() {
    // 数据库结构升级后的一次性提示条（服务端渲染，点过就不再显示）
    const bar = document.getElementById("db-notice");
    const close = document.getElementById("db-notice-close");
    if (!bar || !close) return;
    close.onclick = async () => {
      bar.remove();
      try {
        await API.dismissDbNotice();
      } catch (e) {
        // 关不掉也不影响使用，下次启动会再提示
      }
    };
  }

  async function boot() {
    bindNoticeBar();
    restoreLifetime();
    restorePrivacy();
    try {
      await loadGroups();
      await loadMailboxes();
      if (!state.mailboxes.length && !state.groups.length) {
        // 首次运行给个默认分组，不算打扰
      }
      const visible = visibleMailboxes();
      if (visible.length) await selectMailbox(visible[0].id);
      // 页面重开后接上仍在后台运行的任务
      if (window.TMJobs) TMJobs.resume();
    } catch (e) {
      toast(e.message, true);
    }
    // 不再做任何自动轮询：抓信由用户手动触发批量任务
  }

  boot();
})();
