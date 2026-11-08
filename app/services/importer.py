"""账户导入：解析文本/Excel，校验 uuid，去重后入库。

导入只依赖 uuid（站点凭证）+ 助记词（备份用）。邮箱地址在导入时向站点
查询 `api_check_emails.php` 获得，同时顺便验证 uuid 是否有效。
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from .. import store
from .client import OneTimeEmailClient, SiteError, normalize_emails
from .xlsx_reader import XlsxError, read_rows

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# 表头行识别：含有这些词但没有 uuid 的行直接跳过，不算错误
HEADER_HINTS = ("uuid", "助记", "短语", "口令", "恢复码", "phrase", "mnemonic", "recovery")

MAX_ROWS = 300


class ParseError(Exception):
    """文件格式问题（如损坏的 xlsx），属于调用方输入错误。"""
_SEPARATORS = re.compile(r"[\s,;|，、\t]+")


def _split_phrase(rest: str) -> str:
    """清理 uuid 之外的残留文本，得到助记词。"""
    cleaned = _SEPARATORS.sub(" ", rest).strip(" :：-—=")
    return cleaned.strip()


def parse_text(text: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """把多行文本解析成 (候选列表, 无效行列表)。

    每行只需要包含 uuid，助记词可选（顺序随意，用逗号/制表符/空格分隔均可）。
    """
    candidates: List[Dict[str, Any]] = []
    invalid: List[Dict[str, Any]] = []
    for index, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = raw_line.replace("\ufeff", "").strip()
        if not line or line.startswith("#"):
            continue
        match = UUID_RE.search(line)
        if not match:
            lowered = line.lower()
            if any(hint in lowered for hint in HEADER_HINTS):
                continue  # 表头，静默跳过
            invalid.append({"line": index, "text": line[:120]})
            continue
        uuid = match.group(0).lower()
        phrase = _split_phrase(line[: match.start()] + " " + line[match.end():])
        candidates.append({"line": index, "uuid": uuid, "phrase": phrase})
    return candidates, invalid


def parse_excel(data: bytes) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """读取 xlsx 第一个工作表，把每行拼成文本后复用 parse_text。

    这样列顺序、有无表头都不影响解析；解析器是自带的极简 xlsx 读取器，
    不依赖 openpyxl。
    """
    try:
        rows = read_rows(data)
    except XlsxError as exc:
        raise ParseError(str(exc)) from exc

    lines: List[str] = []
    for row in rows:
        cells = [cell for cell in row if cell]
        if cells:
            lines.append(" ".join(cells))
    return parse_text("\n".join(lines))


def _dedup_index() -> Tuple[set, set]:
    uuids, emails = store.existing_identity_sets()
    return uuids, emails


def import_accounts(text: str, group_id: Optional[int] = None,
                    auto_renew: bool = True) -> Dict[str, Any]:
    """执行导入，返回导入结果汇总。"""
    candidates, invalid = parse_text(text)
    return _run(candidates, invalid, group_id, auto_renew)


def import_from_excel(data: bytes, group_id: Optional[int] = None,
                      auto_renew: bool = True) -> Dict[str, Any]:
    candidates, invalid = parse_excel(data)
    return _run(candidates, invalid, group_id, auto_renew)


def _run(candidates: List[Dict[str, Any]], invalid: List[Dict[str, Any]],
         group_id: Optional[int], auto_renew: bool) -> Dict[str, Any]:
    if group_id is not None and not store.get_group(group_id):
        group_id = None

    if len(candidates) > MAX_ROWS:
        candidates = candidates[:MAX_ROWS]

    known_uuids, known_emails = _dedup_index()
    imported: List[Dict[str, Any]] = []
    duplicated: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    # 同一批里重复的行也要识别出来
    seen_uuids: Dict[str, int] = {}

    for item in candidates:
        uuid = item["uuid"]
        if uuid in known_uuids:
            existing = store.find_mailbox_by_uuid(uuid)
            duplicated.append({
                "line": item["line"],
                "uuid": uuid,
                "email": (existing or {}).get("email", ""),
                "reason": "该 uuid 已在列表中",
            })
            continue
        if uuid in seen_uuids:
            duplicated.append({
                "line": item["line"],
                "uuid": uuid,
                "email": "",
                "reason": f"与本文件第 {seen_uuids[uuid]} 行重复",
            })
            continue

        client = OneTimeEmailClient()
        try:
            data = client.check_emails(uuid)
        except SiteError as exc:
            failed.append({"line": item["line"], "uuid": uuid, "error": str(exc)})
            continue

        email = str(data.get("email") or "").strip()
        if not email:
            failed.append({"line": item["line"], "uuid": uuid, "error": "站点未返回邮箱地址"})
            continue
        if email.lower() in known_emails:
            existing_email = email
            duplicated.append({
                "line": item["line"],
                "uuid": uuid,
                "email": existing_email,
                "reason": "该邮箱地址已在列表中",
            })
            continue

        phrase = item["phrase"] or str(data.get("recovery_phrase") or "")
        try:
            mailbox = store.create_mailbox(
                email=email,
                uuid=uuid,
                recovery_phrase=phrase,
                lifetime=data.get("lifetime") or "30d",
                auto_renew=auto_renew,
                cookies=client.cookies,
                note="",
                mailbox_type=1,
                group_id=group_id,
            )
        except Exception as exc:  # 唯一键冲突兜底
            failed.append({"line": item["line"], "uuid": uuid, "error": f"写入失败：{exc}"})
            continue

        new_mail = 0
        for mail in normalize_emails(data.get("emails", [])):
            if store.upsert_email(mailbox["id"], mail):
                new_mail += 1

        known_uuids.add(uuid)
        known_emails.add(email.lower())
        seen_uuids[uuid] = item["line"]
        imported.append({
            "id": mailbox["id"],
            "email": email,
            "uuid": uuid,
            "line": item["line"],
            "new_mail": new_mail,
        })

    store.add_log(
        "info", "import",
        f"导入完成：成功 {len(imported)}，重复 {len(duplicated)}，"
        f"失败 {len(failed)}，无效 {len(invalid)}",
    )

    return {
        "total": len(candidates) + len(invalid),
        "parsed": len(candidates),
        "imported": imported,
        "duplicated": duplicated,
        "invalid": invalid,
        "failed": failed,
    }
