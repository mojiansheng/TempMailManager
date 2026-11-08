"""数据访问层：mailboxes / emails / logs 的读写。"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .config import RENEW_INTERVAL_SECONDS
from .database import get_conn

MB_FIELDS = (
    "id, email, uuid, recovery_phrase, lifetime, auto_renew, note, "
    "mailbox_type, group_id, status, sort_order, "
    "created_at, last_checked_at, last_renewed_at, last_error"
)


def _row_to_mailbox(row) -> Dict[str, Any]:
    data = dict(row)
    data["auto_renew"] = bool(data.get("auto_renew"))
    # 对外统一用 type 表示邮箱类型（当前固定 1）
    data["type"] = data.pop("mailbox_type", 1) or 1
    return data


# ----------------------------- mailboxes -----------------------------

def create_mailbox(
    email: str,
    uuid: str,
    recovery_phrase: str = "",
    lifetime: str = "30d",
    auto_renew: bool = True,
    cookies: str = "",
    note: str = "",
    mailbox_type: int = 1,
    group_id: Optional[int] = None,
) -> Dict[str, Any]:
    now = _now()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM mailboxes"
        ).fetchone()
        next_sort = (row["m"] or 0) + 1
        cur = conn.execute(
            """INSERT INTO mailboxes
               (email, uuid, recovery_phrase, lifetime, auto_renew, cookies, note,
                mailbox_type, group_id, sort_order, created_at, last_checked_at, last_renewed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (email, uuid, recovery_phrase, lifetime, int(auto_renew), cookies,
             note, int(mailbox_type), group_id, next_sort, now, now, now),
        )
        new_id = cur.lastrowid
    return get_mailbox(new_id)  # type: ignore[return-value]


def list_mailboxes() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {MB_FIELDS} FROM mailboxes ORDER BY sort_order, id DESC"
        ).fetchall()
        counts = {
            r["mailbox_id"]: r["c"]
            for r in conn.execute(
                "SELECT mailbox_id, COUNT(*) AS c FROM emails GROUP BY mailbox_id"
            ).fetchall()
        }
        unread = {
            r["mailbox_id"]: r["c"]
            for r in conn.execute(
                "SELECT mailbox_id, COUNT(*) AS c FROM emails "
                "WHERE is_read = 0 GROUP BY mailbox_id"
            ).fetchall()
        }
    result = []
    for row in rows:
        item = _row_to_mailbox(row)
        item["email_count"] = counts.get(item["id"], 0)
        item["unread_count"] = unread.get(item["id"], 0)
        result.append(item)
    return result


def get_mailbox(mailbox_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {MB_FIELDS} FROM mailboxes WHERE id = ?", (mailbox_id,)
        ).fetchone()
    return _row_to_mailbox(row) if row else None


def get_mailbox_secret(mailbox_id: int) -> Optional[Dict[str, Any]]:
    """含 cookies 的完整记录，仅内部服务层使用。"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
    return dict(row) if row else None


def update_mailbox(mailbox_id: int, **fields) -> Optional[Dict[str, Any]]:
    allowed = {"auto_renew", "note", "lifetime", "status", "cookies",
               "last_checked_at", "last_renewed_at", "last_error", "group_id", "sort_order"}
    payload = {k: v for k, v in fields.items() if k in allowed}
    if not payload:
        return get_mailbox(mailbox_id)
    if "auto_renew" in payload:
        payload["auto_renew"] = int(bool(payload["auto_renew"]))
    assignments = ", ".join(f"{k} = ?" for k in payload)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE mailboxes SET {assignments} WHERE id = ?",
            (*payload.values(), mailbox_id),
        )
    return get_mailbox(mailbox_id)


def delete_mailbox(mailbox_id: int) -> bool:
    with get_conn() as conn:
        conn.execute("DELETE FROM emails WHERE mailbox_id = ?", (mailbox_id,))
        cur = conn.execute("DELETE FROM mailboxes WHERE id = ?", (mailbox_id,))
        return cur.rowcount > 0


def list_due_for_renewal() -> List[Dict[str, Any]]:
    """自动续期开启、且距上次续期超过间隔的邮箱。"""
    threshold = _fmt(datetime.now() - timedelta(seconds=RENEW_INTERVAL_SECONDS))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {MB_FIELDS} FROM mailboxes "
            "WHERE auto_renew = 1 AND status = 'active' "
            "AND (last_renewed_at IS NULL OR last_renewed_at <= ?)",
            (threshold,),
        ).fetchall()
    return [_row_to_mailbox(r) for r in rows]


# ----------------------------- groups -----------------------------

def list_groups() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, parent_id, sort_order, created_at FROM groups ORDER BY sort_order, id"
        ).fetchall()
        counts = {
            r["group_id"]: r["c"]
            for r in conn.execute(
                "SELECT group_id, COUNT(*) AS c FROM mailboxes "
                "WHERE group_id IS NOT NULL GROUP BY group_id"
            ).fetchall()
        }
    out = []
    for row in rows:
        item = dict(row)
        item["mailbox_count"] = counts.get(item["id"], 0)
        out.append(item)
    return out


def get_group(group_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, parent_id, sort_order, created_at FROM groups WHERE id = ?", (group_id,)
        ).fetchone()
    return dict(row) if row else None


def create_group(name: str, parent_id: Optional[int] = None) -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM groups"
        ).fetchone()
        next_sort = (row["m"] or 0) + 1
        cur = conn.execute(
            "INSERT INTO groups (name, parent_id, sort_order, created_at) VALUES (?, ?, ?, ?)",
            (name, parent_id, next_sort, _now()),
        )
        new_id = cur.lastrowid
    return get_group(new_id)  # type: ignore[return-value]


def update_group(group_id: int, name: Optional[str] = None,
                 parent_id: Optional[int] = None, set_parent: bool = False) -> Optional[Dict[str, Any]]:
    fields: Dict[str, Any] = {}
    if name is not None:
        fields["name"] = name
    if set_parent:
        fields["parent_id"] = parent_id
    if fields:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with get_conn() as conn:
            conn.execute(
                f"UPDATE groups SET {assignments} WHERE id = ?",
                (*fields.values(), group_id),
            )
    return get_group(group_id)


def delete_group(group_id: int) -> List[int]:
    """递归删除分组及其子分组，返回被删除的分组 id 列表。"""
    removed: List[int] = []
    with get_conn() as conn:
        stack = [group_id]
        while stack:
            current = stack.pop()
            removed.append(current)
            children = conn.execute(
                "SELECT id FROM groups WHERE parent_id = ?", (current,)
            ).fetchall()
            stack.extend(r["id"] for r in children)
        placeholders = ",".join("?" * len(removed))
        conn.execute(
            f"UPDATE mailboxes SET group_id = NULL WHERE group_id IN ({placeholders})",
            removed,
        )
        conn.execute(f"DELETE FROM groups WHERE id IN ({placeholders})", removed)
    return removed


def reorder_groups(ordered_ids: List[int]) -> None:
    """按给定顺序重写分组 sort_order（拖拽排序用）。"""
    with get_conn() as conn:
        for index, gid in enumerate(ordered_ids, start=1):
            conn.execute("UPDATE groups SET sort_order = ? WHERE id = ?", (index, gid))


def reorder_mailboxes(ordered_ids: List[int]) -> None:
    """按给定顺序重写邮箱 sort_order（拖拽排序用）。"""
    with get_conn() as conn:
        for index, mid in enumerate(ordered_ids, start=1):
            conn.execute("UPDATE mailboxes SET sort_order = ? WHERE id = ?", (index, mid))


def move_mailboxes(ids: List[int], group_id: Optional[int]) -> int:
    """把一批邮箱移到指定分组（group_id 为 None 表示未分组），返回受影响行数。"""
    clean = [int(i) for i in ids if str(i).isdigit() or isinstance(i, int)]
    if not clean:
        return 0
    marks = ",".join("?" for _ in clean)
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE mailboxes SET group_id = ? WHERE id IN ({marks})",
            (group_id, *clean),
        )
        return cur.rowcount


def descendant_group_ids(group_id: int) -> List[int]:
    """包含自身在内的整棵子树 id。"""
    with get_conn() as conn:
        ids: List[int] = []
        stack = [group_id]
        while stack:
            current = stack.pop()
            ids.append(current)
            children = conn.execute(
                "SELECT id FROM groups WHERE parent_id = ?", (current,)
            ).fetchall()
            stack.extend(r["id"] for r in children)
    return ids


# ----------------------------- 导入辅助 -----------------------------

def existing_identity_sets() -> tuple:
    """返回 (已有 uuid 集合, 已有 email 集合)，用于导入去重。"""
    with get_conn() as conn:
        uuids = {r["uuid"] for r in conn.execute("SELECT uuid FROM mailboxes").fetchall()}
        emails = {r["email"].lower() for r in conn.execute("SELECT email FROM mailboxes").fetchall()}
    return uuids, emails


def find_mailbox_by_uuid(uuid: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {MB_FIELDS} FROM mailboxes WHERE uuid = ?", (uuid,)
        ).fetchone()
    return _row_to_mailbox(row) if row else None


# ----------------------------- emails -----------------------------

def upsert_email(mailbox_id: int, item: Dict[str, Any]) -> bool:
    """写入一封邮件，返回是否为新邮件。"""
    remote_id = str(item.get("id") or item.get("remote_id") or "")
    if not remote_id:
        return False
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM emails WHERE mailbox_id = ? AND remote_id = ?",
            (mailbox_id, remote_id),
        ).fetchone()
        if exists:
            conn.execute(
                """UPDATE emails SET sender = ?, subject = ?, received_at = ?,
                   body_html = ?, body_text = ?, fetched_at = ?
                   WHERE mailbox_id = ? AND remote_id = ?""",
                (
                    item.get("sender", ""),
                    item.get("subject", ""),
                    item.get("received_at", ""),
                    item.get("body_html", "") or "",
                    item.get("body_text", "") or "",
                    _now(),
                    mailbox_id,
                    remote_id,
                ),
            )
            return False
        conn.execute(
            """INSERT INTO emails
               (mailbox_id, remote_id, sender, subject, received_at,
                body_html, body_text, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mailbox_id,
                remote_id,
                item.get("sender", ""),
                item.get("subject", ""),
                item.get("received_at", ""),
                item.get("body_html", "") or "",
                item.get("body_text", "") or "",
                _now(),
            ),
        )
        return True


def list_emails(mailbox_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, remote_id, sender, subject, received_at, is_read, fetched_at,
                      substr(COALESCE(NULLIF(body_text, ''), body_html), 1, 160) AS preview
               FROM emails WHERE mailbox_id = ? ORDER BY id DESC""",
            (mailbox_id,),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["is_read"] = bool(item["is_read"])
        out.append(item)
    return out


def get_email(email_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["is_read"] = bool(item["is_read"])
    return item


def mark_read(email_id: int, read: bool = True) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE emails SET is_read = ? WHERE id = ?",
                     (int(read), email_id))


def clear_emails(mailbox_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM emails WHERE mailbox_id = ?", (mailbox_id,))
        return cur.rowcount


# ----------------------------- logs -----------------------------

def add_log(level: str, action: str, message: str, mailbox_id: Optional[int] = None) -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO logs (level, action, mailbox_id, message, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (level, action, mailbox_id, message[:2000], _now()),
            )
            _LOG_WRITE_COUNTER["n"] += 1
            if _LOG_WRITE_COUNTER["n"] % 50 == 0:
                conn.execute(
                    "DELETE FROM logs WHERE id NOT IN "
                    "(SELECT id FROM logs ORDER BY id DESC LIMIT 2000)"
                )
    except Exception:
        pass


def recent_logs(limit: int = 200, level: str = "") -> List[Dict[str, Any]]:
    with get_conn() as conn:
        if level:
            rows = conn.execute(
                "SELECT * FROM logs WHERE level = ? ORDER BY id DESC LIMIT ?",
                (level, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


# ----------------------------- helpers -----------------------------

def _now() -> str:
    return _fmt(datetime.now())


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------- settings kv -----------------------------

def kv_get(key: str, default: Any = None) -> Any:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings_kv WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except ValueError:
        return default


def kv_set(key: str, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings_kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, payload),
        )


def kv_delete(key: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM settings_kv WHERE key = ?", (key,))


# ----------------------------- jobs -----------------------------

def create_job(job_id: str, kind: str, total: int, lifetime: str = "30d",
               targets: Optional[List[Dict[str, Any]]] = None) -> None:
    """建任务，同时把目标写进 job_items（seq 决定顺序，便于恢复时展示）。"""
    started = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO jobs (id, kind, status, total, done, lifetime, current,
                                 started_at)
               VALUES (?, ?, 'running', ?, 0, ?, '', ?)""",
            (job_id, kind, total, lifetime, started),
        )
        for seq, target in enumerate(targets or [], start=1):
            conn.execute(
                """INSERT INTO job_items (job_id, seq, mailbox_id, email, ok, at)
                   VALUES (?, ?, ?, ?, 0, ?)""",
                (job_id, seq, target.get("id"), target.get("email", ""), started),
            )


def update_job_progress(job_id: str, done: int, current: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET done = ?, current = ? WHERE id = ?",
            (done, current or "", job_id),
        )


def finish_job_item(job_id: str, seq: int, ok: bool, new_count: int = 0,
                    total_count: int = 0, error: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE job_items
               SET ok = ?, new_count = ?, total_count = ?, error = ?, at = ?
               WHERE job_id = ? AND seq = ?""",
            (int(ok), new_count, total_count, (error or "")[:500], _now(), job_id, seq),
        )


def finish_job(job_id: str, status: str, error: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, current = '', finished_at = ?, error = ? WHERE id = ?",
            (status, _now(), (error or "")[:500], job_id),
        )


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        job = dict(row)
        items = conn.execute(
            "SELECT seq, mailbox_id, email, ok, new_count, total_count, error, at "
            "FROM job_items WHERE job_id = ? ORDER BY seq",
            (job_id,),
        ).fetchall()
    job["items"] = [dict(i) for i in items]
    return job


def list_jobs(limit: int = 30) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY started_at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def active_job() -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        job = dict(row)
        items = conn.execute(
            "SELECT seq, mailbox_id, email, ok, new_count, total_count, error, at "
            "FROM job_items WHERE job_id = ? ORDER BY seq",
            (job["id"],),
        ).fetchall()
    job["items"] = [dict(i) for i in items]
    return job


def mark_interrupted_jobs() -> int:
    """进程重启后，把上次遗留的 running 任务标记为中断。"""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'interrupted', current = '', finished_at = ?, "
            "error = '程序重启，任务中断' WHERE status = 'running'",
            (_now(),),
        )
        return cur.rowcount


def prune_jobs(keep: int = 200) -> int:
    with get_conn() as conn:
        stale = conn.execute(
            "SELECT id FROM jobs ORDER BY started_at DESC, rowid DESC LIMIT -1 OFFSET ?",
            (keep,),
        ).fetchall()
        ids = [r["id"] for r in stale]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM job_items WHERE job_id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", ids)
    return len(ids)


# ----------------------------- logs 维护 -----------------------------

_LOG_WRITE_COUNTER = {"n": 0}


def clear_logs() -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM logs")
        return cur.rowcount


def prune_logs(keep: int = 2000) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM logs WHERE id NOT IN "
            "(SELECT id FROM logs ORDER BY id DESC LIMIT ?)",
            (keep,),
        )
        return cur.rowcount


# ----------------------------- 前端请求日志 -----------------------------

def add_access_log(method: str, path: str, query: str, status: int,
                   duration_ms: int, ip: str = "", body: str = "",
                   error: str = "") -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO access_logs
                   (method, path, query, status, duration_ms, ip, request_body, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (method, path, query[:500], status, duration_ms, ip,
                 (body or "")[:2000], (error or "")[:500], _now()),
            )
            _LOG_WRITE_COUNTER["n"] += 1
            if _LOG_WRITE_COUNTER["n"] % 50 == 0:
                conn.execute(
                    "DELETE FROM access_logs WHERE id NOT IN "
                    "(SELECT id FROM access_logs ORDER BY id DESC LIMIT 5000)"
                )
    except Exception:
        pass


def list_access_logs(limit: int = 200, keyword: str = "",
                     status_min: int = 0) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM access_logs"
    where, params = [], []
    if keyword:
        where.append("(path LIKE ? OR query LIKE ? OR error LIKE ?)")
        params += [f"%{keyword}%"] * 3
    if status_min:
        where.append("status >= ?")
        params.append(status_min)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def clear_access_logs() -> int:
    with get_conn() as conn:
        return conn.execute("DELETE FROM access_logs").rowcount


# ----------------------------- 外部请求日志 -----------------------------

def add_http_log(method: str, url: str, status: int, duration_ms: int,
                 request_body: str = "", response_body: str = "",
                 error: str = "", job_id: str = "",
                 mailbox_id: Optional[int] = None) -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO http_logs
                   (method, url, status, duration_ms, request_body, response_body,
                    error, job_id, mailbox_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (method, url[:1000], status, duration_ms,
                 (request_body or "")[:4000], (response_body or "")[:4000],
                 (error or "")[:500], job_id or "", mailbox_id, _now()),
            )
            _LOG_WRITE_COUNTER["n"] += 1
            if _LOG_WRITE_COUNTER["n"] % 50 == 0:
                conn.execute(
                    "DELETE FROM http_logs WHERE id NOT IN "
                    "(SELECT id FROM http_logs ORDER BY id DESC LIMIT 2000)"
                )
    except Exception:
        pass


def list_http_logs(limit: int = 200, keyword: str = "",
                   only_error: bool = False) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM http_logs"
    where, params = [], []
    if keyword:
        where.append("(url LIKE ? OR response_body LIKE ? OR error LIKE ?)")
        params += [f"%{keyword}%"] * 3
    if only_error:
        where.append("(status >= 400 OR error != '')")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def clear_http_logs() -> int:
    with get_conn() as conn:
        return conn.execute("DELETE FROM http_logs").rowcount


def fix_log_timezone_once() -> int:
    """老版本 logs 表用的是 UTC 时间，这里一次性平移到本地时区。"""
    if store_flag_present("logs_tz_fixed"):
        return 0
    offset = int((datetime.now() - datetime.utcnow()).total_seconds())
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE logs SET created_at = datetime(created_at, ?) WHERE created_at IS NOT NULL",
            (f"{offset} seconds",),
        )
        moved = cur.rowcount
    set_flag("logs_tz_fixed", True)
    return moved


# ----------------------------- kv 旗标 -----------------------------

def store_flag_present(key: str) -> bool:
    return kv_get(f"flag:{key}") is True


def set_flag(key: str, value: Any) -> None:
    kv_set(f"flag:{key}", value)
