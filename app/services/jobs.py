"""批量任务引擎：手动抓信 / 批量续期。

任务主体在后端线程里跑，前端只是"观察者"：
  - 关掉网页、刷新页面都不影响任务继续执行
  - 每次任务的进度与每条结果都写入 SQLite（jobs / job_items 表）
  - 页面重新打开时通过 /api/jobs/active 找回正在跑的任务

同一时刻只允许一个任务在跑（避免两批请求交叉打站点，让「间隔」失去意义）。
"""

import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .. import store, trace
from ..settings_store import next_gap_ms
from .client import SiteError
from . import mailbox_service as svc

MAX_KEEP = 200


class JobBusy(Exception):
    """已有任务在运行。"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def snapshot_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """把数据库里的一条任务记录转成前端用的快照结构。"""
    items = row.get("items") or []
    results = []
    for item in items:
        processed = bool(item.get("ok")) or bool(item.get("error"))
        if not processed:
            continue
        results.append({
            "mailbox_id": item.get("mailbox_id"),
            "email": item.get("email", ""),
            "ok": bool(item.get("ok")),
            "new": item.get("new_count", 0),
            "total": item.get("total_count", 0),
            "error": item.get("error", ""),
            "at": item.get("at", ""),
        })
    success = sum(1 for r in results if r["ok"])
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "total": row.get("total", 0),
        "done": row.get("done", 0),
        "current": row.get("current", ""),
        "success": success,
        "failed": len(results) - success,
        "started_at": row.get("started_at", ""),
        "finished_at": row.get("finished_at"),
        "lifetime": row.get("lifetime", "30d"),
        "error": row.get("error", ""),
        "results": results[-200:],
    }


class Job:
    def __init__(self, kind: str, targets: List[Dict[str, Any]], lifetime: str = "30d"):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind                    # fetch | renew
        self.lifetime = lifetime
        self.targets = targets              # [{id, email}]
        self.total = len(targets)
        self.done = 0
        self.status = "running"             # running | done | cancelled
        self.current = ""
        self.results: List[Dict[str, Any]] = []
        self.cancel_requested = False
        self.started_at = _now()
        self.finished_at: Optional[str] = None

    @property
    def success(self) -> int:
        return sum(1 for r in self.results if r["ok"])

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r["ok"])

    def snapshot(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "current": self.current,
            "success": self.success,
            "failed": self.failed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "lifetime": self.lifetime,
            "error": "",
            "results": self.results[-200:],
        }


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}
        self._current: Optional[Job] = None

    # ---------------- 对外 ----------------
    def create(self, kind: str, targets: List[Dict[str, Any]],
               lifetime: str = "30d") -> Job:
        with self._lock:
            if self._current and self._current.status == "running":
                raise JobBusy("已有任务在运行，请等它结束或先取消。")
            job = Job(kind, targets, lifetime)
            store.create_job(job.id, kind, job.total, lifetime, targets)
            self._jobs[job.id] = job
            self._current = job
            if len(self._jobs) > 20:  # 内存里只留最近的，历史在数据库
                for stale in list(self._jobs)[:-20]:
                    if self._jobs[stale].status != "running":
                        self._jobs.pop(stale, None)

        thread = threading.Thread(target=self._run, args=(job,), daemon=True,
                                  name=f"job-{job.id}")
        thread.start()
        return job

    def active(self) -> Optional[Job]:
        """内存里正在跑的任务（进程重启后为 None）。"""
        with self._lock:
            job = self._current
            return job if job and job.status == "running" else None

    def active_snapshot(self) -> Optional[Dict[str, Any]]:
        job = self.active()
        if job:
            return job.snapshot()
        row = store.active_job()
        return snapshot_from_row(row) if row else None

    def snapshot(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job:
            return job.snapshot()
        row = store.get_job(job_id)
        return snapshot_from_row(row) if row else None

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [snapshot_from_row(row) for row in store.list_jobs(limit)]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job or job.status != "running":
            return False
        job.cancel_requested = True
        return True

    # ---------------- 执行 ----------------
    def _run(self, job: Job) -> None:
        store.add_log("info", job.kind,
                      f"{'抓信' if job.kind == 'fetch' else '续期'}任务开始，共 {job.total} 个邮箱")
        status = "done"
        error = ""
        try:
            for index, target in enumerate(job.targets):
                if job.cancel_requested:
                    status = "cancelled"
                    break
                if index:
                    time.sleep(max(0, next_gap_ms(job.kind)) / 1000.0)
                if job.cancel_requested:
                    status = "cancelled"
                    break
                job.current = target["email"]
                store.update_job_progress(job.id, job.done, job.current)
                result = self._run_one(job, target)
                store.finish_job_item(
                    job.id, index + 1, result["ok"],
                    new_count=result.get("new", 0),
                    total_count=result.get("total", 0),
                    error=result.get("error", ""),
                )
                job.results.append(result)
                job.done += 1
                store.update_job_progress(job.id, job.done, job.current)
        except Exception as exc:  # 兜底，别让线程静默死掉
            error = f"任务异常中止：{exc}"
            job.results.append({"mailbox_id": None, "email": "", "ok": False,
                                "error": error, "at": _now()})
            store.add_log("error", job.kind, f"任务异常：{exc}")
        finally:
            job.status = status
            job.current = ""
            job.finished_at = _now()
            store.finish_job(job.id, status, error)
            store.add_log(
                "info", job.kind,
                f"任务结束：成功 {job.success}，失败 {job.failed}，状态 {status}",
            )
            try:
                store.prune_jobs(MAX_KEEP)
            except Exception:
                pass

    def _run_one(self, job: Job, target: Dict[str, Any]) -> Dict[str, Any]:
        mailbox_id = target["id"]
        base = {"mailbox_id": mailbox_id, "email": target["email"], "at": _now()}
        # 让外部请求日志能关联到任务与邮箱
        trace.set_context(job_id=job.id, mailbox_id=mailbox_id)
        try:
            if job.kind == "fetch":
                stats = svc.refresh_mailbox(mailbox_id)
                return {**base, "ok": True, "new": stats.get("new", 0),
                        "total": stats.get("total", 0), "error": ""}
            svc.renew_mailbox(mailbox_id, lifetime=job.lifetime)
            return {**base, "ok": True, "new": 0, "total": 0, "error": ""}
        except SiteError as exc:
            return {**base, "ok": False, "new": 0, "total": 0, "error": str(exc)}
        except Exception as exc:
            return {**base, "ok": False, "new": 0, "total": 0,
                    "error": f"未预期错误：{exc}"}
        finally:
            trace.clear_context()


def resolve_targets(kind: str, scope: str = "all",
                    ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """把「全部 / 指定 id」解析成任务目标列表。

    续期任务只取开启了自动续期的邮箱；抓信任务不做这个限制。
    """
    mailboxes = store.list_mailboxes()
    if scope != "all":
        wanted = {int(i) for i in (ids or [])}
        mailboxes = [m for m in mailboxes if m["id"] in wanted]
    if kind == "renew":
        mailboxes = [m for m in mailboxes if m.get("auto_renew")]
    return [{"id": m["id"], "email": m["email"]} for m in mailboxes]


manager = JobManager()
