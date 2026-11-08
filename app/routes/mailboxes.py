"""邮箱相关接口。"""

import io
from urllib.parse import quote

from flask import Blueprint, jsonify, request, send_file

from .. import store
from ..config import DEFAULT_LIFETIME, LIFETIME_OPTIONS
from ..services import SiteError
from ..services import importer, xlsx_writer
from ..services import mailbox_service as svc

bp = Blueprint("mailboxes", __name__, url_prefix="/api/mailboxes")

_EXCEL_EXT = (".xlsx", ".xlsm", ".xltx")
_TEXT_EXT = (".txt", ".csv", ".tsv", ".md", ".log")
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_TEMPLATE_NAME = "邮箱导入模板.xlsx"


def _err(message: str, code: int = 400):
    return jsonify({"success": False, "error": message}), code


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


@bp.get("")
def list_mailboxes():
    return jsonify({"success": True, "data": store.list_mailboxes()})


@bp.post("")
def create_mailbox():
    payload = request.get_json(silent=True) or {}
    auto_renew = bool(payload.get("auto_renew", True))
    note = str(payload.get("note", ""))[:200]
    group_id = _as_group_id(payload.get("group_id"))
    lifetime = str(payload.get("lifetime") or DEFAULT_LIFETIME)
    if lifetime not in LIFETIME_OPTIONS:
        return _err(f"不支持的有效期：{lifetime}")
    if group_id is not None and not store.get_group(group_id):
        return _err("分组不存在。", 404)
    try:
        mailbox = svc.create_mailbox(auto_renew=auto_renew, note=note,
                                     group_id=group_id, lifetime=lifetime)
    except SiteError as exc:
        return _err(str(exc), 502)
    except Exception as exc:  # 兜底，避免 500 页面
        return _err(f"创建失败：{exc}", 500)
    return jsonify({"success": True, "data": mailbox}), 201


@bp.get("/import/template")
def download_import_template():
    """下载 Excel 导入模板（表头 + 3 个示例账户）。"""
    data = xlsx_writer.template_bytes()
    resp = send_file(io.BytesIO(data), mimetype=_XLSX_MIME, max_age=0)
    # 同时给出 ASCII 兜底名与 UTF-8 中文名，避免老客户端拿到 ".xlsx"
    resp.headers["Content-Disposition"] = (
        'attachment; filename="mailbox-import-template.xlsx"; '
        f"filename*=UTF-8''{quote(_TEMPLATE_NAME)}"
    )
    return resp


@bp.post("/import")
def import_mailboxes():
    """导入账户：支持 JSON {text, group_id} 与 multipart 文件（txt/csv/xlsx）。"""
    group_id = None
    auto_renew = True
    try:
        if "file" in request.files:
            upload = request.files["file"]
            if not upload or not upload.filename:
                return _err("未选择文件。")
            filename = upload.filename.lower()
            raw = upload.read()
            if not raw:
                return _err("文件是空的。")
            group_id = _as_group_id(request.form.get("group_id"))
            auto_renew = request.form.get("auto_renew", "1") != "0"
            if filename.endswith(_EXCEL_EXT):
                result = importer.import_from_excel(raw, group_id, auto_renew)
            elif filename.endswith(_TEXT_EXT) or "." not in filename:
                result = importer.import_accounts(_decode(raw), group_id, auto_renew)
            else:
                return _err("只支持 txt / csv / xlsx 文件。")
        else:
            payload = request.get_json(silent=True) or {}
            text = str(payload.get("text") or "")
            if not text.strip():
                return _err("没有可导入的内容。")
            group_id = _as_group_id(payload.get("group_id"))
            auto_renew = bool(payload.get("auto_renew", True))
            result = importer.import_accounts(text, group_id, auto_renew)
    except importer.ParseError as exc:
        return _err(str(exc), 400)
    except SiteError as exc:
        return _err(str(exc), 502)
    except Exception as exc:
        return _err(f"导入失败：{exc}", 500)

    return jsonify({"success": True, "data": result})


def _as_group_id(value):
    if value in (None, "", 0, "0", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@bp.get("/<int:mailbox_id>")
def get_mailbox(mailbox_id: int):
    mailbox = store.get_mailbox(mailbox_id)
    if not mailbox:
        return _err("邮箱不存在。", 404)
    return jsonify({"success": True, "data": mailbox})


@bp.patch("/<int:mailbox_id>")
def update_mailbox(mailbox_id: int):
    if not store.get_mailbox(mailbox_id):
        return _err("邮箱不存在。", 404)
    payload = request.get_json(silent=True) or {}
    fields = {}
    if "auto_renew" in payload:
        fields["auto_renew"] = bool(payload["auto_renew"])
    if "note" in payload:
        fields["note"] = str(payload["note"]).strip()[:200]
    if "group_id" in payload:
        gid = payload.get("group_id")
        if gid in (None, "", 0, "0"):
            fields["group_id"] = None
        else:
            try:
                gid = int(gid)
            except (TypeError, ValueError):
                return _err("分组参数不合法。")
            if not store.get_group(gid):
                return _err("分组不存在。", 404)
            fields["group_id"] = gid
    mailbox = store.update_mailbox(mailbox_id, **fields)
    return jsonify({"success": True, "data": mailbox})


@bp.post("/reorder")
def reorder_mailboxes():
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        return _err("ids 必须是邮箱 id 数组。")
    store.reorder_mailboxes(ids)
    return jsonify({"success": True, "data": store.list_mailboxes()})


@bp.delete("/<int:mailbox_id>")
def delete_mailbox(mailbox_id: int):
    remote = request.args.get("remote", "1") != "0"
    if not svc.delete_mailbox(mailbox_id, remote=remote):
        return _err("邮箱不存在。", 404)
    return jsonify({"success": True})


@bp.post("/move")
def move_mailboxes():
    """批量把邮箱移入某个分组（group_id 为 null 表示移到未分组）。"""
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids")
    if not isinstance(ids, list) or not ids:
        return _err("ids 必须是邮箱 id 数组。")
    group_id = _as_group_id(payload.get("group_id"))
    if group_id is not None and not store.get_group(group_id):
        return _err("分组不存在。", 404)
    moved = store.move_mailboxes([int(i) for i in ids], group_id)
    group_name = "未分组"
    if group_id is not None:
        group_name = store.get_group(group_id)["name"]
    store.add_log("info", "move", f"移动 {moved} 个邮箱到「{group_name}」")
    return jsonify({"success": True, "data": {"moved": moved, "group_id": group_id}})


@bp.post("/<int:mailbox_id>/renew")
def renew_mailbox(mailbox_id: int):
    try:
        mailbox = svc.renew_mailbox(mailbox_id)
    except SiteError as exc:
        return _err(str(exc), 502)
    return jsonify({"success": True, "data": mailbox})


@bp.post("/<int:mailbox_id>/refresh")
def refresh_mailbox(mailbox_id: int):
    try:
        stats = svc.refresh_mailbox(mailbox_id)
    except SiteError as exc:
        return _err(str(exc), 502)
    return jsonify({"success": True, "data": stats})


@bp.get("/<int:mailbox_id>/emails")
def list_emails(mailbox_id: int):
    if not store.get_mailbox(mailbox_id):
        return _err("邮箱不存在。", 404)
    return jsonify({"success": True, "data": store.list_emails(mailbox_id)})


@bp.delete("/<int:mailbox_id>/emails")
def clear_emails(mailbox_id: int):
    if not store.get_mailbox(mailbox_id):
        return _err("邮箱不存在。", 404)
    removed = store.clear_emails(mailbox_id)
    store.add_log("info", "clear", f"清空本地邮件 {removed} 封", mailbox_id)
    return jsonify({"success": True, "data": {"removed": removed}})
