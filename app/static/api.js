/* 接口层：统一封装 fetch，返回 data 或抛出可读错误。 */
const API = (() => {
  async function request(url, options = {}) {
    const opt = { headers: {}, ...options };
    const isForm = opt.body instanceof FormData;
    if (opt.body && !isForm && typeof opt.body === "object") {
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(opt.body);
    }
    let resp;
    try {
      resp = await fetch(url, opt);
    } catch (e) {
      throw new Error("网络请求失败，请检查后台是否在运行。");
    }
    let payload = null;
    try {
      payload = await resp.json();
    } catch (e) {
      throw new Error(`服务返回异常（HTTP ${resp.status}）`);
    }
    if (!resp.ok || payload.success === false) {
      throw new Error(payload && payload.error ? payload.error : `请求失败（HTTP ${resp.status}）`);
    }
    return payload.data;
  }

  const json = (method, url, body) => request(url, { method, body });

  return {
    listMailboxes: () => request("/api/mailboxes"),
    createMailbox: (autoRenew, groupId, lifetime) =>
      json("POST", "/api/mailboxes", {
        auto_renew: autoRenew, group_id: groupId ?? null, lifetime: lifetime || null,
      }),
    updateMailbox: (id, patch) => json("PATCH", `/api/mailboxes/${id}`, patch),
    moveMailboxes: (ids, groupId) =>
      json("POST", "/api/mailboxes/move", { ids, group_id: groupId ?? null }),
    deleteMailbox: (id, remote = true) =>
      request(`/api/mailboxes/${id}?remote=${remote ? 1 : 0}`, { method: "DELETE" }),
    renewMailbox: (id) => request(`/api/mailboxes/${id}/renew`, { method: "POST" }),
    refreshMailbox: (id) => request(`/api/mailboxes/${id}/refresh`, { method: "POST" }),
    listEmails: (id) => request(`/api/mailboxes/${id}/emails`),
    clearEmails: (id) => request(`/api/mailboxes/${id}/emails`, { method: "DELETE" }),
    getEmail: (id) => request(`/api/emails/${id}`),
    deleteEmail: (id) => request(`/api/emails/${id}`, { method: "DELETE" }),

    importText: (text, groupId, autoRenew) =>
      json("POST", "/api/mailboxes/import", {
        text, group_id: groupId ?? null, auto_renew: autoRenew,
      }),
    importFile: (file, groupId, autoRenew) => {
      const form = new FormData();
      form.append("file", file);
      if (groupId != null) form.append("group_id", String(groupId));
      form.append("auto_renew", autoRenew ? "1" : "0");
      return request("/api/mailboxes/import", { method: "POST", body: form });
    },

    listGroups: () => request("/api/groups"),
    createGroup: (name, parentId) =>
      json("POST", "/api/groups", { name, parent_id: parentId ?? null }),
    updateGroup: (id, patch) => json("PATCH", `/api/groups/${id}`, patch),
    deleteGroup: (id) => request(`/api/groups/${id}`, { method: "DELETE" }),
    reorderGroups: (ids) => json("POST", "/api/groups/reorder", { ids }),
    reorderMailboxes: (ids) => json("POST", "/api/mailboxes/reorder", { ids }),

    // 批量任务
    createJob: (kind, scope, ids) =>
      json("POST", "/api/jobs", { kind, scope, ids: ids || [] }),
    getJob: (id) => request(`/api/jobs/${id}`),
    listJobs: () => request("/api/jobs"),
    activeJob: () => request("/api/jobs/active"),
    cancelJob: (id) => request(`/api/jobs/${id}/cancel`, { method: "POST" }),

    // 配置
    getSettings: () => request("/api/settings"),
    saveSettings: (patch) => json("PATCH", "/api/settings", patch),
    resetSettings: () => request("/api/settings/reset", { method: "POST" }),

    getLogs: (params = {}) => {
      const q = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") q.set(key, value);
      });
      const qs = q.toString();
      return request(`/api/logs${qs ? `?${qs}` : ""}`);
    },
    clearLogs: (kind) => request(`/api/logs?kind=${kind || "business"}`, { method: "DELETE" }),

    health: () => request("/api/health"),
    // 关闭「数据库已升级」提示条
    dismissDbNotice: () => request("/api/db-notice", { method: "DELETE" }),
  };
})();
