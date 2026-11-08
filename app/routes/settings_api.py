"""设置接口：读写 data/settings.json，附带续期调度状态。"""

from flask import Blueprint, jsonify, request

from .. import settings_store
from ..services.renewer import scheduler

bp = Blueprint("settings", __name__, url_prefix="/api/settings")


def _payload():
    return jsonify({
        "success": True,
        "data": {
            "settings": settings_store.load(),
            "scheduler": scheduler.status(),
        },
    })


@bp.get("")
def get_settings():
    return _payload()


@bp.patch("")
def update_settings():
    patch = request.get_json(silent=True) or {}
    if not isinstance(patch, dict):
        return jsonify({"success": False, "error": "参数不合法。"}), 400
    allowed = {"fetch", "renew"}
    if not allowed & set(patch.keys()):
        return jsonify({"success": False, "error": "没有可更新的配置项。"}), 400
    settings_store.save({k: v for k, v in patch.items() if k in allowed})
    return _payload()


@bp.post("/reset")
def reset_settings():
    settings_store.reset_to_defaults()
    return _payload()
