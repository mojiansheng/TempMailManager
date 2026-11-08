"""批量任务接口：手动抓信 / 批量续期。"""

from flask import Blueprint, jsonify, request

from ..services import jobs

bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")

VALID_KINDS = ("fetch", "renew")


@bp.post("")
def create_job():
    payload = request.get_json(silent=True) or {}
    kind = str(payload.get("kind", "fetch"))
    if kind not in VALID_KINDS:
        return jsonify({"success": False, "error": "任务类型不合法。"}), 400

    scope = str(payload.get("scope", "all"))
    ids = payload.get("ids") or []
    if scope != "all":
        try:
            ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "邮箱 id 不合法。"}), 400
        if not ids:
            return jsonify({"success": False, "error": "请先选择邮箱。"}), 400

    targets = jobs.resolve_targets(kind, scope, ids)
    if not targets:
        message = ("没有勾选自动续期的邮箱。" if kind == "renew"
                   else "没有可抓取的邮箱。")
        return jsonify({"success": False, "error": message}), 400

    try:
        job = jobs.manager.create(kind, targets)
    except jobs.JobBusy as exc:
        return jsonify({"success": False, "error": str(exc)}), 409

    return jsonify({"success": True, "data": job.snapshot()}), 201


@bp.get("")
def list_jobs():
    """历史任务（按开始时间倒序），用于页面重开后查看。"""
    return jsonify({"success": True, "data": jobs.manager.recent(30)})


@bp.get("/active")
def active_job():
    """当前正在跑的任务；没有则 data 为 null。前端打开页面时用它恢复进度。"""
    return jsonify({"success": True, "data": jobs.manager.active_snapshot()})


@bp.get("/<job_id>")
def get_job(job_id: str):
    snapshot = jobs.manager.snapshot(job_id)
    if not snapshot:
        return jsonify({"success": False, "error": "任务不存在。"}), 404
    return jsonify({"success": True, "data": snapshot})


@bp.post("/<job_id>/cancel")
def cancel_job(job_id: str):
    if not jobs.manager.cancel(job_id):
        return jsonify({"success": False, "error": "任务不存在或已结束。"}), 400
    return jsonify({"success": True})
