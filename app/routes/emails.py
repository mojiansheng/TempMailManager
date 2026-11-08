"""邮件相关接口。"""

from flask import Blueprint, jsonify, request

from .. import store

bp = Blueprint("emails", __name__, url_prefix="/api/emails")


@bp.get("/<int:email_id>")
def get_email(email_id: int):
    if not store.get_email(email_id):
        return jsonify({"success": False, "error": "邮件不存在。"}), 404
    store.mark_read(email_id, True)
    return jsonify({"success": True, "data": store.get_email(email_id)})


@bp.post("/<int:email_id>/read")
def set_read(email_id: int):
    if not store.get_email(email_id):
        return jsonify({"success": False, "error": "邮件不存在。"}), 404
    payload = request.get_json(silent=True) or {}
    store.mark_read(email_id, bool(payload.get("read", True)))
    return jsonify({"success": True})


@bp.delete("/<int:email_id>")
def delete_email(email_id: int):
    if not store.get_email(email_id):
        return jsonify({"success": False, "error": "邮件不存在。"}), 404
    from ..database import get_conn

    with get_conn() as conn:
        conn.execute("DELETE FROM emails WHERE id = ?", (email_id,))
    return jsonify({"success": True})
