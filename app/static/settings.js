/* 设置弹窗：抓信间隔、续期模式与时长。依赖 window.TM / API。 */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const el = {
    modal: $("#settings-modal"),
    close: $("#set-close"),
    cancel: $("#set-cancel"),
    save: $("#set-save"),
    reset: $("#set-reset"),
    fetchMode: $("#set-fetch-mode"),
    fetchMs: $("#set-fetch-ms"),
    fetchMin: $("#set-fetch-min"),
    fetchMax: $("#set-fetch-max"),
    renewEnabled: $("#set-renew-enabled"),
    renewMode: $("#set-renew-mode"),
    renewHours: $("#set-renew-hours"),
    renewTime: $("#set-renew-time"),
    renewLifetime: $("#set-renew-lifetime"),
    renewGapMode: $("#set-renew-gap-mode"),
    renewMs: $("#set-renew-ms"),
    renewMin: $("#set-renew-min"),
    renewMax: $("#set-renew-max"),
    renewStatus: $("#set-renew-status"),
  };

  let lifetimes = ["10m", "30m", "1h", "3h", "6h", "24h", "3d", "7d", "15d", "30d"];
  let lifetimeLabels = {
    "10m": "10 分钟", "30m": "30 分钟", "1h": "1 小时", "3h": "3 小时",
    "6h": "6 小时", "24h": "24 小时", "3d": "3 天", "7d": "7 天",
    "15d": "15 天", "30d": "30 天",
  };

  const lifetimeText = (v) => lifetimeLabels[v] || v;

  function applyConditions() {
    const map = {
      "set-fetch-mode": el.fetchMode.value,
      "set-renew-mode": el.renewMode.value,
      "set-renew-gap-mode": el.renewGapMode.value,
    };
    el.modal.querySelectorAll("[data-cond]").forEach((row) => {
      const [key, value] = row.dataset.cond.split(":");
      row.hidden = map[key] !== value;
    });
  }

  function fillForm(data) {
    const { settings, scheduler } = data;
    const f = settings.fetch;
    el.fetchMode.value = f.gap_mode;
    el.fetchMs.value = f.gap_ms;
    el.fetchMin.value = f.gap_min_ms;
    el.fetchMax.value = f.gap_max_ms;

    const r = settings.renew;
    el.renewEnabled.checked = !!r.enabled;
    el.renewMode.value = r.mode;
    el.renewHours.value = r.interval_hours;
    el.renewTime.value = r.daily_time;
    el.renewGapMode.value = r.gap_mode;
    el.renewMs.value = r.gap_ms;
    el.renewMin.value = r.gap_min_ms;
    el.renewMax.value = r.gap_max_ms;

    if (![...el.renewLifetime.options].some((o) => o.value === r.lifetime)) {
      el.renewLifetime.add(new Option(lifetimeText(r.lifetime), r.lifetime));
    }
    el.renewLifetime.value = r.lifetime;

    const last = scheduler && scheduler.last_run ? scheduler.last_run : null;
    el.renewStatus.textContent = last
      ? `上次自动续期：${last}${scheduler.running_job ? " · 当前有续期任务在跑" : ""}`
      : "还没有自动续期记录（保存后由调度器按设置触发）。";
    applyConditions();
  }

  async function load() {
    const [data, health] = await Promise.all([
      API.getSettings(),
      API.health().catch(() => null),
    ]);
    if (health && Array.isArray(health.lifetimes)) {
      lifetimes = health.lifetimes;
      if (health.lifetime_labels) lifetimeLabels = health.lifetime_labels;
      el.renewLifetime.innerHTML = lifetimes
        .map((x) => `<option value="${x}">${lifetimeText(x)}</option>`).join("");
    }
    fillForm(data);
  }

  async function open() {
    el.modal.hidden = false;
    try {
      await load();
    } catch (e) {
      TM.toast(e.message, true);
    }
  }

  function close() {
    el.modal.hidden = true;
  }

  function num(input, fallback) {
    const value = Number(input.value);
    return Number.isFinite(value) ? value : fallback;
  }

  async function save() {
    el.save.disabled = true;
    try {
      const patch = {
        fetch: {
          gap_mode: el.fetchMode.value,
          gap_ms: num(el.fetchMs, 500),
          gap_min_ms: num(el.fetchMin, 300),
          gap_max_ms: num(el.fetchMax, 1500),
        },
        renew: {
          enabled: el.renewEnabled.checked,
          mode: el.renewMode.value,
          interval_hours: num(el.renewHours, 24),
          daily_time: el.renewTime.value || "03:00",
          lifetime: el.renewLifetime.value || "30d",
          gap_mode: el.renewGapMode.value,
          gap_ms: num(el.renewMs, 800),
          gap_min_ms: num(el.renewMin, 500),
          gap_max_ms: num(el.renewMax, 2000),
        },
      };
      const data = await API.saveSettings(patch);
      fillForm(data);
      TM.toast("设置已保存，立即生效");
    } catch (e) {
      TM.toast(e.message, true);
    } finally {
      el.save.disabled = false;
    }
  }

  async function reset() {
    if (!confirm("恢复默认设置？抓信间隔会回到固定 500ms，续期回到每 24 小时。")) return;
    try {
      const data = await API.resetSettings();
      fillForm(data);
      TM.toast("已恢复默认设置");
    } catch (e) {
      TM.toast(e.message, true);
    }
  }

  [el.fetchMode, el.renewMode, el.renewGapMode].forEach((node) => {
    node.addEventListener("change", applyConditions);
  });

  el.save.onclick = save;
  el.reset.onclick = reset;
  el.cancel.onclick = close;
  el.close.onclick = close;
  el.modal.addEventListener("click", (e) => {
    if (e.target === el.modal) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !el.modal.hidden) close();
  });

  const btn = document.getElementById("btn-settings");
  if (btn) btn.onclick = open;

  window.TMSettings = { open, close };
})();
