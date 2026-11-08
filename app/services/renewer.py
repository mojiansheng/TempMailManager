"""续期调度器。

按 settings.json 的配置触发「批量续期任务」：
  - interval 模式：距上次续期超过 N 小时就触发
  - daily   模式：每天到点（HH:MM）触发一次

真正干活的是 services/jobs.py 的任务引擎（按配置的毫秒间隔逐个执行），
调度器只负责「什么时候开跑」。
"""

import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from .. import settings_store, store
from ..config import DATA_DIR
from . import jobs

log = logging.getLogger("tempmail.scheduler")

STATE_KEY = "scheduler"
LEGACY_STATE_PATH = DATA_DIR / "schedule_state.json"
TICK_SECONDS = 30


def _read_state() -> Dict[str, Any]:
    """调度状态存在数据库里，进程重启不丢。"""
    state = store.kv_get(STATE_KEY)
    if isinstance(state, dict):
        return state
    # 兼容老版本写在 json 文件里的状态
    legacy: Dict[str, Any] = {}
    if LEGACY_STATE_PATH.exists():
        try:
            legacy = json.loads(LEGACY_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            legacy = {}
        if isinstance(legacy, dict) and legacy:
            store.kv_set(STATE_KEY, legacy)
        try:
            LEGACY_STATE_PATH.replace(LEGACY_STATE_PATH.with_suffix(".json.migrated"))
        except OSError:
            pass
    return legacy if isinstance(legacy, dict) else {}


def _write_state(state: Dict[str, Any]) -> None:
    try:
        store.kv_set(STATE_KEY, state)
    except Exception as exc:
        log.warning("写入调度状态失败: %s", exc)


def _parse_daily(value: str) -> Optional[Tuple[int, int]]:
    try:
        hour, minute = str(value).split(":")
        return int(hour), int(minute)
    except (ValueError, AttributeError):
        return None


class RenewScheduler:
    def __init__(self, tick: int = TICK_SECONDS):
        self.tick = max(5, int(tick))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="renew-scheduler", daemon=True)
        self._thread.start()
        log.info("续期调度器已启动，巡检间隔 %ss", self.tick)

    def stop(self) -> None:
        self._stop.set()

    # ---------------- 判定 ----------------
    def _due(self, cfg: Dict[str, Any], state: Dict[str, Any]) -> bool:
        now = datetime.now()
        if cfg.get("mode") == "daily":
            parsed = _parse_daily(cfg.get("daily_time", "03:00"))
            if not parsed:
                return False
            hour, minute = parsed
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now < target:
                return False
            return state.get("last_daily_date") != now.strftime("%Y-%m-%d")

        last_raw = state.get("last_renew_run")
        if not last_raw:
            return True
        try:
            last = datetime.strptime(last_raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return True
        hours = int(cfg.get("interval_hours", 24))
        return now - last >= timedelta(hours=max(1, hours))

    def run_once(self, force: bool = False) -> Optional[str]:
        """巡检一次；返回新建任务的 id（没触发则 None）。"""
        if jobs.manager.active():
            return None

        cfg = settings_store.load()["renew"]
        if not cfg.get("enabled") and not force:
            return None

        state = _read_state()
        if not force and not self._due(cfg, state):
            return None

        targets = jobs.resolve_targets("renew", "all")
        if not targets:
            return None

        try:
            job = jobs.manager.create("renew", targets, lifetime=cfg.get("lifetime", "30d"))
        except jobs.JobBusy:
            return None

        now = datetime.now()
        state["last_renew_run"] = now.strftime("%Y-%m-%d %H:%M:%S")
        state["last_daily_date"] = now.strftime("%Y-%m-%d")
        state["last_job_id"] = job.id
        _write_state(state)
        log.info("已触发续期任务 %s，共 %s 个邮箱", job.id, job.total)
        store.add_log("info", "renew", f"调度触发续期任务，共 {job.total} 个邮箱")
        return job.id

    def status(self) -> Dict[str, Any]:
        cfg = settings_store.load()["renew"]
        state = _read_state()
        active = jobs.manager.active()
        return {
            "enabled": bool(cfg.get("enabled")),
            "mode": cfg.get("mode"),
            "interval_hours": cfg.get("interval_hours"),
            "daily_time": cfg.get("daily_time"),
            "lifetime": cfg.get("lifetime"),
            "last_run": state.get("last_renew_run"),
            "last_daily_date": state.get("last_daily_date"),
            "running_job": active.snapshot() if active else None,
        }

    # ---------------- 线程 ----------------
    def _run(self) -> None:
        self._stop.wait(5)
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:  # 单次失败不影响后续
                log.warning("调度巡检异常: %s", exc)
            self._stop.wait(self.tick)


scheduler = RenewScheduler()
