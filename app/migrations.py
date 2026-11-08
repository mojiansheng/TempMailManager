"""数据库结构版本化迁移。

设计：
- `schema_version` 表记录当前结构版本号（单行表）。
- `MIGRATIONS`：{版本号: 升级函数}，从当前版本依次执行到最新版本。
- `STRUCT_CHECKS`：{版本号: 判定函数}，结构已经满足该版本时跳过升级函数
  （全新库的建表语句就是最新结构，不必再跑一遍加列）。
- 所有升级只做「加列 / 加表 / 回填数据」，绝不删除或改写既有数据。
- 真需要升级时，先把整库备份成 `tempmail.db.bak-v<旧版本>`，再执行迁移。
- 旧库（没有版本表）视为版本 0；结构版本比程序新的库不会被降级。
- 升级结果写入 logs 表（action=db_migrate），界面「运行日志」里能直接看到。

可独立运行：`python -m app.migrations [db路径]`。
应用启动时 `init_db()` 也会自动检查并升级。
"""

import json
import sqlite3
import time
from pathlib import Path

from .config import DB_PATH

# 当前最新结构版本：新增结构变更时 +1，并在 MIGRATIONS / STRUCT_CHECKS 里补一项
LATEST_VERSION = 1

# 最近一次实际发生的升级，供启动日志打印；没有升级时为 None
LAST_UPGRADE = None


def _table_columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _max_sort(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COALESCE(MAX(sort_order), 0) AS m FROM {table}").fetchone()
    return row[0] if row and row[0] is not None else 0


def _db_file(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    return (row[2] or "") if row else ""


# ----------------------------- 各版本升级 -----------------------------

def _migrate_to_v1(conn: sqlite3.Connection) -> None:
    """v1：分组与邮箱支持拖动排序（groups.sort_order / mailboxes.sort_order）。"""
    # 旧库可能还没经历过历史加列，这里一并兜底（幂等）
    mb_cols = _table_columns(conn, "mailboxes")
    if "mailbox_type" not in mb_cols:
        conn.execute("ALTER TABLE mailboxes ADD COLUMN mailbox_type INTEGER NOT NULL DEFAULT 1")
    if "group_id" not in mb_cols:
        conn.execute("ALTER TABLE mailboxes ADD COLUMN group_id INTEGER")

    g_cols = _table_columns(conn, "groups")
    if "sort_order" not in g_cols:
        conn.execute("ALTER TABLE groups ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")

    mb_cols = _table_columns(conn, "mailboxes")
    if "sort_order" not in mb_cols:
        conn.execute("ALTER TABLE mailboxes ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")

    # 回填：老数据按 id 升序给一个稳定排序值（不影响原数据，只补新列的值）
    base = _max_sort(conn, "groups")
    for offset, row in enumerate(conn.execute(
            "SELECT id FROM groups ORDER BY id").fetchall(), start=1):
        conn.execute("UPDATE groups SET sort_order = ? WHERE id = ?",
                     (base + offset, row[0]))

    base = _max_sort(conn, "mailboxes")
    for offset, row in enumerate(conn.execute(
            "SELECT id FROM mailboxes ORDER BY id").fetchall(), start=1):
        conn.execute("UPDATE mailboxes SET sort_order = ? WHERE id = ?",
                     (base + offset, row[0]))

    conn.execute("CREATE INDEX IF NOT EXISTS idx_mailboxes_group ON mailboxes (group_id)")


MIGRATIONS = {
    1: _migrate_to_v1,
}


def _struct_ok_v1(conn: sqlite3.Connection) -> bool:
    """结构是否已满足 v1（两列都在）。返回 True 表示无需执行升级函数。"""
    return ("sort_order" in _table_columns(conn, "groups")
            and "sort_order" in _table_columns(conn, "mailboxes"))


STRUCT_CHECKS = {
    1: _struct_ok_v1,
}


# ----------------------------- 版本管理 -----------------------------

def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("UPDATE schema_version SET version = ?, "
                 "updated_at = datetime('now', 'localtime')", (version,))


def _backup_db(conn: sqlite3.Connection, from_version: int):
    """升级前整库快照，返回备份文件名；无法备份时返回 None。"""
    path = _db_file(conn)
    if not path:
        return None
    src = Path(path)
    if not src.exists():
        return None
    bak = src.with_name(f"{src.name}.bak-v{from_version}")
    if bak.exists():
        bak = src.with_name(f"{src.name}.bak-v{from_version}-{time.strftime('%Y%m%d%H%M%S')}")
    try:
        conn.commit()  # backup 要求源连接没有未提交的写事务
        target = sqlite3.connect(str(bak))
        try:
            conn.backup(target)
        finally:
            target.close()
    except (sqlite3.Error, OSError):
        return None
    return bak.name


def _log_upgrade(conn: sqlite3.Connection, from_version: int, to_version: int,
                 backup, steps) -> None:
    """把升级结果写进运行日志，并在页面上留一条一次性提示（用户点「知道了」消失）。"""
    try:
        msg = f"数据库结构 v{from_version} → v{to_version}（升级 {steps}）"
        if backup:
            msg += f"，升级前已备份 {backup}"
        conn.execute("INSERT INTO logs (level, action, message) "
                     "VALUES ('info', 'db_migrate', ?)", (msg,))

        notice = json.dumps({
            "from": from_version,
            "to": to_version,
            "backup": backup or "",
            "steps": steps,
            "at": time.strftime("%Y-%m-%d %H:%M"),
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO settings_kv (key, value) VALUES ('db_upgrade_notice', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (notice,))
        conn.commit()
    except sqlite3.Error:
        # 日志 / 设置表不可用不影响升级结果
        pass


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    """补齐只在迁移函数里建过的索引（幂等，启动时跑一次）。

    背景：v1.1.0/1.1.1 的 `STRUCT_CHECKS` 让全新库跳过 `_migrate_to_v1`，
    而 `idx_mailboxes_group` 当时只写在迁移函数里 → 新装的库缺这个索引。
    这里统一兜底，老库新库都保证有。
    """
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mailboxes_group "
                     "ON mailboxes (group_id)")
    except sqlite3.Error:
        pass


def migrate(conn: sqlite3.Connection, verify: bool = True) -> int:
    """把数据库升级到最新结构，返回最终版本号。幂等，可重复调用。

    verify=False 时只按版本号判断、不做结构比对（每次连接调用用，省一次 PRAGMA）。
    """
    global LAST_UPGRADE

    conn.execute("""CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER NOT NULL,
                        updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                    )""")
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        # 还没有版本记录：完全没有业务表的是全新库（建表语句已是最新），
        # 有业务表的是老库（无版本表时代建的），从 0 开始升。
        has_tables = bool(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='groups'"
        ).fetchone())
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        if not has_tables:
            _set_version(conn, LATEST_VERSION)
        conn.commit()
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()

    current = int(row[0])

    # 库比程序新：不降级，避免老版本程序改坏新库
    if current > LATEST_VERSION:
        return current

    # 兜底：版本号声称已是新版，但列被外部改没了 → 重跑（迁移本身幂等）
    if verify and current >= LATEST_VERSION and not _struct_ok_v1(conn):
        current = 0

    # 结构已是最新时，仍补齐历史遗留的索引（幂等，只多一次 CREATE INDEX IF NOT EXISTS）
    if verify:
        _ensure_indexes(conn)

    if current >= LATEST_VERSION:
        return LATEST_VERSION

    # 结构已满足的版本不必执行升级函数（如全新库），只补版本号
    pending = [v for v in range(current + 1, LATEST_VERSION + 1)
               if not STRUCT_CHECKS.get(v, lambda _c: False)(conn)]
    backup = _backup_db(conn, current) if pending else None

    steps = []
    for version in range(current + 1, LATEST_VERSION + 1):
        fn = MIGRATIONS.get(version)
        if fn and version in pending:
            fn(conn)
        _set_version(conn, version)
        steps.append(version)
    conn.commit()

    if pending:
        _log_upgrade(conn, current, LATEST_VERSION, backup, steps)
        LAST_UPGRADE = {
            "from": current,
            "to": LATEST_VERSION,
            "backup": backup,
            "steps": steps,
        }
    return LATEST_VERSION


def migrate_file(db_path=DB_PATH) -> int:
    """对指定数据库文件执行升级（供独立脚本使用）。"""
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        result = migrate(conn)
        conn.commit()
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    # 允许直接运行：python app/migrations.py [db路径]
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from app.config import DB_PATH
        from app.migrations import LAST_UPGRADE as _last, migrate_file
    else:
        from .config import DB_PATH
        from .migrations import LAST_UPGRADE as _last, migrate_file

    path = sys.argv[1] if len(sys.argv) > 1 else str(DB_PATH)
    version = migrate_file(path)
    print(f"数据库结构已就绪，当前版本: v{version} ({path})")
    if _last:
        print(f"本次已从 v{_last['from']} 升级到 v{_last['to']}")
        if _last.get("backup"):
            print(f"升级前备份：{_last['backup']}")
    else:
        print("无需升级。")
