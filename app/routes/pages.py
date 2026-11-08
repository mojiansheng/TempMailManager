"""页面与系统接口。"""

from flask import Blueprint, jsonify, render_template, request

from .. import store, trace
from ..config import (
    DEFAULT_LIFETIME,
    LIFETIME_LABELS,
    LIFETIME_OPTIONS,
    RENEW_INTERVAL_SECONDS,
    lifetime_choices,
)

bp = Blueprint("pages", __name__)


@bp.get("/")
def index():
    return render_template(
        "index.html",
        lifetime_choices=lifetime_choices(),
        default_lifetime=DEFAULT_LIFETIME,
        db_notice=store.kv_get("db_upgrade_notice"),
    )


@bp.delete("/api/db-notice")
def dismiss_db_notice():
    """关闭页面上的「数据库已升级」提示条（一次性，点过就不再显示）。"""
    store.kv_delete("db_upgrade_notice")
    return jsonify({"success": True, "data": {"dismissed": True}})


@bp.get("/api/health")
def health():
    return jsonify({
        "success": True,
        "data": {
            "lifetimes": LIFETIME_OPTIONS,
            "lifetime_labels": LIFETIME_LABELS,
            "default_lifetime": DEFAULT_LIFETIME,
            "renew_interval_seconds": RENEW_INTERVAL_SECONDS,
        },
    })


def _sanitize_http(row):
    """出库脱敏：uuid 只留前 8 位，助记词/cookie 打码。"""
    row = dict(row)
    row["url"] = trace.sanitize(row.get("url", ""), 1000)
    row["request_body"] = trace.sanitize(row.get("request_body", ""))
    row["response_body"] = trace.sanitize(row.get("response_body", ""))
    row["error"] = trace.sanitize(row.get("error", ""), 500)
    return row


def _sanitize_access(row):
    row = dict(row)
    row["request_body"] = trace.sanitize(row.get("request_body", ""), 600)
    row["error"] = trace.sanitize(row.get("error", ""), 500)
    return row


@bp.get("/api/logs")
def logs():
    """日志中心：kind=business|system|access|http。"""
    kind = request.args.get("kind", "business")
    level = request.args.get("level", "").strip()
    keyword = request.args.get("keyword", "").strip()
    try:
        limit = min(500, max(1, int(request.args.get("limit", 200))))
    except ValueError:
        limit = 200

    if kind == "access":
        rows = store.list_access_logs(limit, keyword,
                                      int(request.args.get("status_min", 0) or 0))
        rows = [_sanitize_access(r) for r in rows]
    elif kind == "http":
        rows = store.list_http_logs(limit, keyword,
                                    request.args.get("only_error") == "1")
        raw = request.args.get("raw") == "1"   # 诊断时需要完整原文
        rows = [r if raw else _sanitize_http(r) for r in rows]
    elif kind == "system":
        rows = [r for r in store.recent_logs(limit * 2, level)
                if r["action"] in ("system", "server")][:limit]
    else:
        rows = [r for r in store.recent_logs(limit * 2, level)
                if r["action"] not in ("system", "server")][:limit]
    return jsonify({"success": True, "data": rows})


@bp.delete("/api/logs")
def clear_logs():
    kind = request.args.get("kind", "business")
    if kind == "access":
        removed = store.clear_access_logs()
        store.add_log("info", "clear", f"清空请求日志 {removed} 条")
    elif kind == "http":
        removed = store.clear_http_logs()
        store.add_log("info", "clear", f"清空外部请求日志 {removed} 条")
    else:
        removed = store.clear_logs()
        store.add_log("info", "clear", f"清空日志 {removed} 条")
    return jsonify({"success": True, "data": {"removed": removed}})
