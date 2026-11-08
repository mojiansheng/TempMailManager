/* 分组树：渲染、新建、重命名、移动、删除、拖动排序。依赖 window.TM / TMDialog。 */
(() => {
  const STORAGE_KEY = "tm_expanded_groups";
  const expanded = new Set(loadExpanded());

  function loadExpanded() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function saveExpanded() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...expanded]));
    } catch (e) { /* 隐私模式下忽略 */ }
  }

  function countOf(groupId) {
    const ids = TM.subtreeIds(groupId);
    return TM.state.mailboxes.filter((m) => m.group_id && ids.has(m.group_id)).length;
  }

  function rowShell({ kind, id, name, count, depth, hasChildren, active }) {
    const caret = kind === "group" && hasChildren
      ? `<span class="g-caret ${expanded.has(id) ? "open" : ""}" data-act="toggle"
              title="${expanded.has(id) ? "收起子分组" : "展开子分组"}">▸</span>`
      : `<span class="g-caret ghost">▸</span>`;
    const actions = kind === "group"
      ? `<span class="g-actions">
           <button class="g-act" data-act="add-child" title="新建子分组">＋</button>
           <button class="g-act" data-act="rename" title="重命名">✎</button>
           <button class="g-act danger" data-act="remove" title="删除分组">✕</button>
         </span>`
      : "";
    return `
      <div class="g-row ${active ? "active" : ""}" data-kind="${kind}"
           ${id != null ? `data-id="${id}"` : ""} style="padding-left:${8 + depth * 14}px">
        ${caret}
        <span class="g-name" title="${TM.esc(name)}">${TM.esc(name)}</span>
        <span class="g-count">${count}</span>
        ${actions}
      </div>`;
  }

  function render() {
    const { el, state } = TM;
    const roots = TM.childGroups(null);
    const parts = [
      rowShell({
        kind: "all", id: null, name: "全部邮箱", count: state.mailboxes.length,
        depth: 0, hasChildren: false, active: state.selectedGroup === "all",
      }),
      rowShell({
        kind: "ungrouped", id: null, name: "未分组",
        count: state.mailboxes.filter((m) => !m.group_id).length,
        depth: 0, hasChildren: false, active: state.selectedGroup === "ungrouped",
      }),
    ];

    const walk = (list, depth) => {
      list.forEach((g) => {
        const children = TM.childGroups(g.id);
        const isOpen = expanded.has(g.id) || children.length === 0;
        parts.push(rowShell({
          kind: "group", id: g.id, name: g.name, count: countOf(g.id),
          depth, hasChildren: children.length > 0,
          active: String(state.selectedGroup) === String(g.id),
        }));
        if (children.length && isOpen) walk(children, depth + 1);
      });
    };
    walk(roots, 0);

    parts.push(`<div class="drag-hint">拖动分组：同级排序 / 拖到分组上放入其下<br>拖动邮箱到分组：直接移入（也可用邮箱区右上角 ☑ 批量移入）</div>`);
    el.groupTree.innerHTML = parts.join("") ||
      `<div class="empty">还没有分组</div>`;
    bindGroupDrag();
  }

  async function createGroup(parentId = null) {
    const name = await TMDialog.input({
      title: parentId ? "新建子分组" : "新建分组",
      label: parentId ? "输入子分组名称（例如：项目A / 测试账号）" : "输入分组名称（例如：项目A / 测试账号）",
      placeholder: "分组名称",
      confirmText: "创建",
    });
    if (name == null) return;
    try {
      await API.createGroup(name, parentId);
      if (parentId) expanded.add(parentId);
      await TM.reload();
      TM.toast("分组已创建");
    } catch (e) {
      TM.toast(e.message, true);
    }
  }

  async function renameGroup(id) {
    const group = TM.state.groups.find((g) => g.id === id);
    if (!group) return;
    const name = await TMDialog.input({
      title: "重命名分组",
      label: `当前名称：${group.name}`,
      value: group.name,
      placeholder: "新的分组名称",
      confirmText: "重命名",
    });
    if (name == null || name === group.name) return;
    try {
      await API.updateGroup(id, { name });
      await TM.reload();
      TM.toast("已重命名");
    } catch (e) {
      TM.toast(e.message, true);
    }
  }

  async function removeGroup(id) {
    const group = TM.state.groups.find((g) => g.id === id);
    if (!group) return;
    const sub = TM.subtreeIds(id).size - 1;
    const msg = sub > 0
      ? `确定删除分组「${group.name}」？\n其下 ${sub} 个子分组会一起删除，组内邮箱会移到「未分组」，不会被删除。`
      : `确定删除分组「${group.name}」？\n组内邮箱会移到「未分组」，不会被删除。`;
    const ok = await TMDialog.confirm({
      title: "删除分组",
      message: msg,
      confirmText: "删除",
      danger: true,
    });
    if (!ok) return;
    try {
      await API.deleteGroup(id);
      if (String(TM.state.selectedGroup) === String(id)) TM.state.selectedGroup = "all";
      await TM.reload();
      TM.toast("分组已删除");
    } catch (e) {
      TM.toast(e.message, true);
    }
  }

  /* ---------------- 拖动：分组排序/嵌套，邮箱拖进分组 ---------------- */
  let dragSrcId = null;
  const MAIL_MIME = "application/x-tm-mailbox";

  const groupOf = (id) => TM.state.groups.find((g) => g.id === id);

  function isMailboxDrag(e) {
    return [...(e.dataTransfer.types || [])].includes(MAIL_MIME);
  }

  /** 行内上/中/下三区：上下 30% 用于同级排序，中间用于「放入」。 */
  function zoneOf(row, clientY) {
    const rect = row.getBoundingClientRect();
    if (clientY < rect.top + rect.height * 0.3) return "before";
    if (clientY > rect.bottom - rect.height * 0.3) return "after";
    return "into";
  }

  function clearMarks(tree) {
    tree.querySelectorAll(".drop-into, .drop-before, .drop-after")
      .forEach((n) => n.classList.remove("drop-into", "drop-before", "drop-after"));
  }

  function bindGroupDrag() {
    const tree = document.getElementById("group-tree");
    if (!tree) return;

    tree.querySelectorAll('.g-row[data-kind="group"]').forEach((row) => {
      row.draggable = true;

      row.ondragstart = (e) => {
        dragSrcId = Number(row.dataset.id);
        row.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", String(dragSrcId)); } catch (_) {}
      };
      row.ondragend = () => {
        row.classList.remove("dragging");
        clearMarks(tree);
        dragSrcId = null;
      };
    });

    // 所有行（含「未分组」）都是放置目标：拖邮箱进来 = 移入分组
    tree.querySelectorAll(".g-row").forEach((row) => {
      const kind = row.dataset.kind;
      const rowId = row.dataset.id ? Number(row.dataset.id) : null;

      row.ondragover = (e) => {
        if (isMailboxDrag(e)) {
          if (kind === "all") return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
          clearMarks(tree);
          row.classList.add("drop-into");
          return;
        }
        if (dragSrcId == null || rowId == null || rowId === dragSrcId) return;
        if (kind === "ungrouped") {
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
          clearMarks(tree);
          row.classList.add("drop-into");
          return;
        }
        if (kind !== "group") return;
        if (TM.subtreeIds(dragSrcId).has(rowId)) return; // 不能拖进自己或自己的子孙
        const src = groupOf(dragSrcId);
        const dst = groupOf(rowId);
        if (!src || !dst) return;
        // 跨层级没有「前后」的概念，一律按放入处理
        let zone = zoneOf(row, e.clientY);
        if (zone !== "into" && src.parent_id !== dst.parent_id) zone = "into";
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        clearMarks(tree);
        row.classList.add(zone === "into" ? "drop-into"
          : zone === "before" ? "drop-before" : "drop-after");
      };

      row.ondragleave = () => clearMarks(tree);

      row.ondrop = async (e) => {
        e.preventDefault();
        clearMarks(tree);

        // 1) 邮箱拖进分组
        if (isMailboxDrag(e)) {
          const ids = (window.TM && TM.draggingMailboxIds) || [];
          if (!ids.length) return;
          const target = kind === "ungrouped" ? null : rowId;
          try {
            await API.moveMailboxes(ids, target);
            await TM.reload();
            const name = target ? (groupOf(target) || {}).name : "未分组";
            TM.toast(`已移动 ${ids.length} 个邮箱到「${name}」`);
          } catch (err) {
            TM.toast(err.message, true);
          }
          return;
        }

        // 2) 分组拖动
        if (dragSrcId == null) return;
        const srcId = dragSrcId;
        const src = groupOf(srcId);
        if (!src) return;

        // 拖到「未分组」行 = 移到顶层
        if (kind === "ungrouped") {
          if (src.parent_id == null) return;
          try {
            await API.updateGroup(srcId, { parent_id: null });
            await TM.reload();
            TM.toast(`「${src.name}」已移到顶层`);
          } catch (err) {
            TM.toast(err.message, true);
          }
          return;
        }

        if (kind !== "group" || rowId == null || rowId === srcId) return;
        const dst = groupOf(rowId);
        if (!dst) return;
        if (TM.subtreeIds(srcId).has(rowId)) return;

        const zone = zoneOf(row, e.clientY);
        try {
          if (zone === "into" || src.parent_id !== dst.parent_id) {
            // 放入目标分组
            await API.updateGroup(srcId, { parent_id: rowId });
            expanded.add(rowId);
            saveExpanded();
            await TM.reload();
            TM.toast(`「${src.name}」已放入「${dst.name}」`);
          } else {
            // 同一父级内排序：插到目标前/后
            const siblings = TM.childGroups(src.parent_id).map((g) => g.id);
            siblings.splice(siblings.indexOf(srcId), 1);
            let idx = siblings.indexOf(rowId);
            if (idx < 0) idx = siblings.length;
            if (zone === "after") idx += 1;
            siblings.splice(idx, 0, srcId);
            await API.reorderGroups(siblings);
            await TM.reload();
            TM.toast("分组顺序已保存");
          }
        } catch (err) {
          TM.toast(err.message, true);
        }
      };
    });
  }

  function selectGroup(kind, id) {
    TM.state.selectedGroup = kind === "group" ? Number(id)
      : kind === "ungrouped" ? "ungrouped" : "all";
    render();
    TM.loadMailboxes();
  }

  document.addEventListener("click", (event) => {
    const tree = document.getElementById("group-tree");
    if (!tree || !tree.contains(event.target)) return;

    const row = event.target.closest(".g-row");
    if (!row) return;
    const kind = row.dataset.kind;
    const id = row.dataset.id ? Number(row.dataset.id) : null;
    const act = event.target.closest("[data-act]")?.dataset.act;

    if (act === "toggle") {
      if (!id) return;
      expanded.has(id) ? expanded.delete(id) : expanded.add(id);
      saveExpanded();
      render();
      return;
    }
    if (act === "add-child") {
      createGroup(id);
      return;
    }
    if (act === "rename") {
      renameGroup(id);
      return;
    }
    if (act === "remove") {
      removeGroup(id);
      return;
    }
    if (kind === "all") {
      selectGroup("all");
    } else if (kind === "ungrouped") {
      selectGroup("ungrouped");
    } else {
      selectGroup("group", id);
    }
  });

  const btnNew = document.getElementById("btn-new-group");
  if (btnNew) btnNew.onclick = () => createGroup(null);

  window.TMGroups = { render, createGroup, renameGroup, removeGroup, selectGroup };
})();
