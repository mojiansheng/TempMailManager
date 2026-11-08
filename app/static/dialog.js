/* 通用弹窗：输入框与确认框，替代原生 prompt/confirm（原生弹窗样式难看且不可定制）。依赖 window.TM。 */
(() => {
  const overlay = document.createElement("div");
  overlay.className = "modal dialog-modal";
  overlay.hidden = true;
  overlay.innerHTML = `
    <div class="dialog-box">
      <div class="dialog-head">
        <h3 class="dialog-title"></h3>
        <button class="icon-btn dialog-x" type="button" title="关闭">✕</button>
      </div>
      <div class="dialog-body">
        <p class="dialog-msg"></p>
        <input class="dialog-input" type="text" maxlength="50" hidden>
        <select class="dialog-select" hidden></select>
      </div>
      <div class="dialog-foot">
        <button class="btn ghost dialog-cancel" type="button">取消</button>
        <button class="btn primary dialog-ok" type="button">确定</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const el = {
    overlay,
    box: overlay.querySelector(".dialog-box"),
    title: overlay.querySelector(".dialog-title"),
    msg: overlay.querySelector(".dialog-msg"),
    input: overlay.querySelector(".dialog-input"),
    select: overlay.querySelector(".dialog-select"),
    cancel: overlay.querySelector(".dialog-cancel"),
    ok: overlay.querySelector(".dialog-ok"),
    x: overlay.querySelector(".dialog-x"),
  };
  let resolver = null;
  let mode = "confirm"; // confirm | input | select

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

  function open({ title, message, value = "", placeholder = "", confirmText = "确定",
                  danger = false, withInput = false, withSelect = false,
                  options = [], selectValue = "" }) {
    return new Promise((resolve) => {
      resolver = resolve;
      mode = withInput ? "input" : withSelect ? "select" : "confirm";
      el.title.textContent = title || "确认";
      el.msg.innerHTML = message || "";
      el.msg.hidden = !message;
      el.input.hidden = mode !== "input";
      el.select.hidden = mode !== "select";
      if (mode === "input") {
        el.input.value = value || "";
        el.input.placeholder = placeholder || "";
      }
      if (mode === "select") {
        el.select.innerHTML = options
          .map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`)
          .join("");
        el.select.value = String(selectValue);
      }
      el.ok.textContent = confirmText || "确定";
      el.ok.classList.toggle("danger", !!danger);
      overlay.hidden = false;
      // 显示动画
      requestAnimationFrame(() => el.box.classList.add("open"));
      setTimeout(() => {
        if (mode === "input") {
          el.input.focus();
          if (value) el.input.select();
        } else if (mode === "select") {
          el.select.focus();
        } else {
          el.ok.focus();
        }
      }, 30);
    });
  }

  function close(result) {
    if (overlay.hidden) return;
    el.box.classList.remove("open");
    overlay.hidden = true;
    if (resolver) {
      resolver(result);
      resolver = null;
    }
  }

  // 点确定：输入模式返回 trim 后的值（空值视为取消），选择模式返回选中值，确认模式返回 true
  el.ok.onclick = () => {
    if (mode === "confirm") {
      close(true);
    } else if (mode === "input") {
      const v = el.input.value.trim();
      close(v || null);
    } else {
      close(el.select.value);
    }
  };
  el.cancel.onclick = () => close(null);
  el.x.onclick = () => close(null);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close(null);
  });
  el.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") el.ok.click();
  });

  // Esc 关闭（与其他弹窗一致的全局处理已存在时这里不重复绑 document）
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) close(null);
  });

  /**
   * 输入弹窗（替代 prompt）：返回 trim 后的字符串；取消/清空返回 null。
   */
  function input({ title, label, value = "", placeholder = "", confirmText = "确定" }) {
    return open({ title, message: label, value, placeholder, confirmText, withInput: true });
  }

  /**
   * 确认弹窗（替代 confirm）：确认返回 true，取消返回 null。
   */
  function confirm({ title, message, confirmText = "确定", danger = false }) {
    return open({ title, message, confirmText, danger }).then((v) => !!v);
  }

  /**
   * 下拉选择弹窗：确定返回选中值（字符串），取消返回 null。
   * options: [{ value, label }]，value 可含空字符串表示「未分组」这类空值。
   */
  function select({ title, label, options = [], value = "", confirmText = "确定" }) {
    return open({
      title, message: label, options, selectValue: value, confirmText, withSelect: true,
    });
  }

  window.TMDialog = { input, confirm, select, close };
})();
