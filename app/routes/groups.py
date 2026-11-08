"""分组相关接口。"""

from flask import Blueprint, jsonify, request

from .. import store
from ..services import GroupError
from ..services import group_service as svc

bp = Blueprint("groups", __name__, url_prefix="/api/groups")


def _err(message: str, code: int = 400):
    return jsonify({"success": False, "error": message}), code


@bp.get("")
def list_groups():
    return jsonify({"success": True, "data": store.list_groups()})


@bp.post("")
def create_group():
    payload = request.get_json(silent=True) or {}
    try:
        group = svc.create_group(payload.get("name", ""), payload.get("parent_id"))
    except GroupError as exc:
        return _err(str(exc))
    return jsonify({"success": True, "data": group}), 201


@bp.patch("/<int:group_id>")
def update_group(group_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        group = svc.update_group(
            group_id,
            name=payload.get("name"),
            parent_id=payload.get("parent_id"),
            has_parent="parent_id" in payload,
        )
    except GroupError as exc:
        if not store.get_group(group_id):
            return _err(str(exc), 404)
        return _err(str(exc))
    return jsonify({"success": True, "data": group})


@bp.post("/reorder")
def reorder_groups():
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        return _err("ids 必须是分组 id 数组。")
    store.reorder_groups(ids)
    return jsonify({"success": True, "data": store.list_groups()})


@bp.delete("/<int:group_id>")
def delete_group(group_id: int):
    try:
        result = svc.delete_group(group_id)
    except GroupError as exc:
        return _err(str(exc), 404)
    return jsonify({"success": True, "data": result})
