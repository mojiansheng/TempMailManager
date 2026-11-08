"""日志采集辅助：脱敏 + 线程上下文 + 外部请求记录。

uuid 等同于邮箱密码，助记词等同备份密钥，所以写日志前必须打码，
只保留前 8 位便于关联，避免日志泄露账户所有权。
"""

import re
import threading
from typing import Optional

from . import store

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
PHRASE_RE = re.compile(r'("recovery_phrase"\s*:\s*")[^"]*(")')
COOKIE_RE = re.compile(r"(PHPSESSID=)[^;\s\"']+")

_local = threading.local()


def set_context(job_id: str = "", mailbox_id: Optional[int] = None) -> None:
    """给当前线程打上任务/邮箱标记，外部请求日志会自动带上。"""
    _local.job_id = job_id or ""
    _local.mailbox_id = mailbox_id


def clear_context() -> None:
    _local.job_id = ""
    _local.mailbox_id = None


def get_context() -> dict:
    return {
        "job_id": getattr(_local, "job_id", "") or "",
        "mailbox_id": getattr(_local, "mailbox_id", None),
    }


def sanitize(text: str, limit: int = 4000) -> str:
    """uuid 保留前 8 位、助记词与 cookie 打码，并截断长度。"""
    if not text:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = UUID_RE.sub(lambda m: m.group(0)[:8] + "…", str(text))
    text = PHRASE_RE.sub(lambda m: m.group(1) + "***" + m.group(2), text)
    text = COOKIE_RE.sub(r"\1***", text)
    return text[:limit]


def record_http(method: str, url: str, status: int, duration_ms: int,
                request_body: str = "", response_body: str = "",
                error: str = "", sanitize_on_write: bool = False) -> None:
    """写外部请求日志。

    默认入库原文（排查问题需要完整凭证）；只有显式传 sanitize_on_write=True
    才在写入时脱敏。前端读取时统一走脱敏出口。
    """
    ctx = get_context()
    if sanitize_on_write:
        url = sanitize(url, 1000)
        request_body = sanitize(request_body)
        response_body = sanitize(response_body)
        error = sanitize(error, 500)
    store.add_http_log(
        method=method,
        url=url[:1000],
        status=status,
        duration_ms=duration_ms,
        request_body=request_body[:4000],
        response_body=response_body[:4000],
        error=error[:500],
        job_id=ctx["job_id"],
        mailbox_id=ctx["mailbox_id"],
    )
