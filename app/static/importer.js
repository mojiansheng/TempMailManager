/* 导入弹窗：粘贴文本 / 文本文件 / Excel。依赖 window.TM。 */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const el = {
    modal: $("#import-modal"),
    close: $("#import-close"),
    cancel: $("#import-cancel"),
    run: $("#import-run"),
    group: $("#import-group"),
    text: $("#import-text"),
    file: $("#import-file"),
    excel: $("#import-excel"),
    result: $("#import-result"),
    autoRenew: $("#import-auto-renew"),
  };

  let tab = "paste";

  // 三种分隔符各演示一次：逗号 / 制表符 / 空格
  const SAMPLE = [
    "# 一行一个账户：uuid 必填，助记词可选，顺序随意",
    "# 分隔符支持逗号、制表符或空格；# 开头的行会被忽略",
    "6f1b9d24-3a7e-4c58-9b02-8e4d17ac5f63, over bulk slice alert dove uncle sketch weekend orphan online balcony fly",
    "2d8c40f7-91b6-4a3e-8c75-5f0e62b9d418\tdegree hurry alert access faint assault adjust october marine figure flat luggage",
    "b4e72a58-06d3-4f19-a8c6-31d95e7f20ab  success awful alcohol gossip recipe give fetch bracket brand calm trend ethics",
  ].join("\n");

  function renderSample() {
    ["format-sample-paste", "format-sample-file"].forEach((id) => {
      const node = document.getElementById(id);
      if (node) node.textContent = SAMPLE;
    });
    const fill = document.getElementById("import-fill-sample");
    if (fill) {
      fill.onclick = () => {
        el.text.value = SAMPLE;
        el.text.focus();
        TM.toast("已填入示例，可直接改成你的账户");
      };
    }
  }

  function groupOptions() {
    const { state, childGroups, esc } = TM;
    const parts = [`<option value="">不分组</option>`];
    const walk = (parentId, depth) => {
      childGroups(parentId).forEach((g) => {
        parts.push(`<option value="${g.id}">${"　".repeat(depth)}${esc(g.name)}</option>`);
        walk(g.id, depth + 1);
      });
    };
    walk(null, 0);
    if (!state.groups.length) return `<option value="">不分组（还没有分组）</option>`;
    return parts.join("");
  }

  function open() {
    el.group.innerHTML = groupOptions();
    const sel = TM.state.selectedGroup;
    if (sel !== "all" && sel !== "ungrouped") el.group.value = String(sel);
    el.result.hidden = true;
    el.result.innerHTML = "";
    el.modal.hidden = false;
    switchTab("paste");
    el.text.focus();
  }

  function close() {
    el.modal.hidden = true;
  }

  function switchTab(name) {
    tab = name;
    document.querySelectorAll("#import-modal .tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === name);
    });
    document.querySelectorAll("#import-modal .tab-pane").forEach((p) => {
      p.hidden = p.dataset.pane !== name;
    });
  }

  document.querySelectorAll("#import-modal .tab").forEach((btn) => {
    btn.onclick = () => switchTab(btn.dataset.tab);
  });

  // 文本文件：读进文本框，切到粘贴页让用户先看一眼
  el.file.onchange = () => {
    const file = el.file.files && el.file.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      el.text.value = String(reader.result || "");
      switchTab("paste");
      TM.toast(`已读入 ${file.name}，确认后点「开始导入」`);
    };
    reader.onerror = () => TM.toast("读取文件失败", true);
    reader.readAsText(file, "utf-8");
  };

  function renderResult(data) {
    const ok = data.imported.length;
    const dup = data.duplicated.length;
    const bad = data.invalid.length;
    const fail = data.failed.length;

    const section = (title, tone, rows) => {
      if (!rows.length) return "";
      return `<div class="res-block">
        <div class="res-title ${tone}">${title}（${rows.length}）</div>
        <div class="res-list">${rows.join("")}</div>
      </div>`;
    };

    const dupRows = data.duplicated.map((d) => `
      <div class="res-row">
        <span class="res-main">${TM.esc(d.email || d.uuid)}</span>
        <span class="res-sub">${TM.esc(d.reason)}${d.email ? ` · uuid ${TM.esc(d.uuid.slice(0, 8))}…` : ""}</span>
      </div>`);

    const okRows = data.imported.map((d) => `
      <div class="res-row">
        <span class="res-main">${TM.esc(d.email)}</span>
        <span class="res-sub">第 ${d.line} 行${d.new_mail ? ` · ${d.new_mail} 封待读邮件` : ""}</span>
      </div>`);

    const badRows = data.invalid.map((d) => `
      <div class="res-row">
        <span class="res-main">第 ${d.line} 行</span>
        <span class="res-sub">${TM.esc(d.text)}</span>
      </div>`);

    const failRows = data.failed.map((d) => `
      <div class="res-row">
        <span class="res-main">${TM.esc(d.uuid || `第 ${d.line} 行`)}</span>
        <span class="res-sub">${TM.esc(d.error)}</span>
      </div>`);

    el.result.innerHTML = `
      <div class="res-summary">
        <span class="chip ok">成功 ${ok}</span>
        <span class="chip dup">重复 ${dup}</span>
        <span class="chip bad">无效 ${bad}</span>
        <span class="chip fail">失败 ${fail}</span>
      </div>
      ${section("已导入", "ok", okRows)}
      ${section("重复，未导入", "dup", dupRows)}
      ${section("无法识别（缺 uuid）", "bad", badRows)}
      ${section("导入失败", "fail", failRows)}`;
    el.result.hidden = false;
  }

  async function run() {
    const groupId = el.group.value ? Number(el.group.value) : null;
    const autoRenew = el.autoRenew.checked;

    el.run.disabled = true;
    el.run.classList.add("loading");
    el.result.hidden = true;
    try {
      let data;
      if (tab === "excel") {
        const file = el.excel.files && el.excel.files[0];
        if (!file) throw new Error("请先选择 Excel 文件。");
        data = await API.importFile(file, groupId, autoRenew);
      } else {
        const text = el.text.value.trim();
        if (!text) throw new Error("没有可导入的内容。");
        data = await API.importText(text, groupId, autoRenew);
      }
      renderResult(data);
      await TM.reload();
      const ok = data.imported.length;
      TM.toast(ok ? `导入完成：成功 ${ok} 个` : "没有新增账户", !ok);
    } catch (e) {
      TM.toast(e.message, true);
      el.result.innerHTML = `<div class="res-empty">${TM.esc(e.message)}</div>`;
      el.result.hidden = false;
    } finally {
      el.run.disabled = false;
      el.run.classList.remove("loading");
    }
  }

  el.run.onclick = run;
  el.cancel.onclick = close;
  el.close.onclick = close;
  el.modal.addEventListener("click", (e) => {
    if (e.target === el.modal) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !el.modal.hidden) close();
  });

  const btnImport = document.getElementById("btn-import");
  if (btnImport) btnImport.onclick = open;

  renderSample();

  window.TMImport = { open, close };
})();
