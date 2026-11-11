"""邮箱业务逻辑：创建、同步收信、续期、删除。"""

from datetime import datetime
from typing import Any, Dict, Optional

from .. import store
from ..config import DEFAULT_LIFETIME
from .client import OneTimeEmailClient, SiteError, normalize_emails


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_mailbox(auto_renew: bool = True, note: str = "",
                   group_id: Optional[int] = None,
                   lifetime: str = DEFAULT_LIFETIME) -> Dict[str, Any]:
    client = OneTimeEmailClient()
    data, cookies = client.create_inbox(lifetime)
    mailbox = store.create_mailbox(
        email=data["email"],
        uuid=data["uuid"],
        recovery_phrase=data.get("recovery_phrase", ""),
        lifetime=data.get("lifetime", DEFAULT_LIFETIME),
        auto_renew=auto_renew,
        cookies=cookies,
        note=note,
        mailbox_type=1,
        group_id=group_id,
    )
    store.add_log("info", "create", f"创建邮箱 {data['email']}", mailbox["id"])
    return mailbox


def refresh_mailbox(mailbox_id: int) -> Dict[str, Any]:
    """拉取该邮箱的最新邮件，返回统计。"""
    mailbox = store.get_mailbox_secret(mailbox_id)
    if not mailbox:
        raise SiteError("邮箱不存在。")

    client = OneTimeEmailClient(mailbox.get("cookies") or "")
    try:
        data = client.check_emails(mailbox["uuid"])
    except SiteError as exc:
        store.update_mailbox(mailbox_id, last_error=str(exc), last_checked_at=_now())
        store.add_log("error", "fetch", f"收信失败：{exc}", mailbox_id)
        raise

    new_count = 0
    for item in normalize_emails(data.get("emails", [])):
        if store.upsert_email(mailbox_id, item):
            new_count += 1

    current_lifetime = data.get("lifetime") or mailbox.get("lifetime")
    store.update_mailbox(
        mailbox_id,
        last_checked_at=_now(),
        last_error="",
        cookies=client.cookies or mailbox.get("cookies") or "",
        lifetime=current_lifetime,
    )
    if new_count:
        store.add_log("info", "fetch", f"收到 {new_count} 封新邮件", mailbox_id)
    return {"new": new_count, "total": len(data.get("emails", [])),
            "lifetime": current_lifetime}


def renew_mailbox(mailbox_id: int, lifetime: Optional[str] = None) -> Dict[str, Any]:
    """把有效期重新设为指定值，实现续期/重置计时。

    lifetime 为 None 时沿用该邮箱当前的有效期（「保持原时长续期」），
    只影响传入的这一个邮箱。
    """
    mailbox = store.get_mailbox_secret(mailbox_id)
    if not mailbox:
        raise SiteError("邮箱不存在。")
    target = lifetime or mailbox.get("lifetime") or DEFAULT_LIFETIME
    client = OneTimeEmailClient(mailbox.get("cookies") or "")
    try:
        client.update_lifetime(mailbox["uuid"], target)
    except SiteError as exc:
        store.update_mailbox(mailbox_id, last_error=str(exc))
        store.add_log("error", "renew", f"续期失败：{exc}", mailbox_id)
        raise

    store.update_mailbox(mailbox_id, lifetime=target,
                         last_renewed_at=_now(), last_error="",
                         cookies=client.cookies or mailbox.get("cookies") or "")
    store.add_log("info", "renew", f"续期成功（{target}）", mailbox_id)
    return store.get_mailbox(mailbox_id)  # type: ignore[return-value]


def delete_mailbox(mailbox_id: int, remote: bool = True) -> bool:
    mailbox = store.get_mailbox_secret(mailbox_id)
    if not mailbox:
        return False
    if remote:
        try:
            OneTimeEmailClient(mailbox.get("cookies") or "").delete_inbox(mailbox["uuid"])
        except SiteError as exc:
            store.add_log("warn", "delete", f"远程删除失败（本地仍删除）：{exc}", mailbox_id)
    ok = store.delete_mailbox(mailbox_id)
    if ok:
        store.add_log("info", "delete", f"已删除邮箱 {mailbox['email']}")
    return ok


def set_auto_renew(mailbox_id: int, enabled: bool) -> Optional[Dict[str, Any]]:
    return store.update_mailbox(mailbox_id, auto_renew=enabled)
