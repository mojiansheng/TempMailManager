"""Flask 应用工厂。"""

import json
import logging
import time

from flask import Flask, g, jsonify, request

from .config import APP_NAME, DATA_DIR
from .database import init_db
from .routes import register_blueprints

log = logging.getLogger("tempmail")


def _setup_logging() -> None:
    """进程日志只走控制台。

    运行日志已全部入库（logs / access_logs / http_logs），tempmail.log
    容易和界面日志混淆，默认不再写文件。
    """
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(sh)


def _log_db_upgrade() -> None:
    """数据库结构升级时在控制台给出明确提示（升级明细同时写入 logs 表）。"""
    from .migrations import LAST_UPGRADE

    if not LAST_UPGRADE:
        return
    tip = f"，升级前已备份 {LAST_UPGRADE['backup']}" if LAST_UPGRADE.get("backup") else ""
    log.info("数据库结构已升级：v%s → v%s%s",
             LAST_UPGRADE["from"], LAST_UPGRADE["to"], tip)


def create_app(start_scheduler: bool = True) -> Flask:
    _setup_logging()
    init_db()
    _log_db_upgrade()

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["JSON_AS_ASCII"] = False
    app.json.ensure_ascii = False

    register_blueprints(app)

    _install_access_log(app)

    # 上次进程被强杀时留下的 running 任务，标记为中断，避免前端一直显示"进行中"
    try:
        from . import store

        interrupted = store.mark_interrupted_jobs()
        if interrupted:
            log.info("已将 %s 个中断任务标记为 interrupted", interrupted)
    except Exception as exc:
        log.warning("处理中断任务失败: %s", exc)

    @app.errorhandler(404)
    def _not_found(_err):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "error": "接口不存在。"}), 404
        return jsonify({"success": False, "error": "页面不存在。"}), 404

    @app.errorhandler(500)
    def _server_error(err):
        log.exception("未处理异常: %s", err)
        try:
            from . import store

            store.add_log("error", "server",
                          f"{request.method} {request.path} 处理失败：{err}"[:500])
        except Exception:
            pass
        return jsonify({"success": False, "error": "服务器内部错误。"}), 500

    @app.after_request
    def _no_cache(resp):
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    try:
        from . import store

        moved = store.fix_log_timezone_once()
        if moved:
            log.info("已修正 %s 条历史日志的时区", moved)
        store.add_log("info", "system",
                      f"{APP_NAME} 启动，数据目录 {DATA_DIR}")
    except Exception as exc:
        log.warning("写入启动日志失败: %s", exc)

    if start_scheduler:
        from .services.renewer import scheduler

        scheduler.start()

    log.info("%s 已就绪", APP_NAME)
    return app


_SKIP_PREFIXES = ("/static/", "/favicon.ico")


def _should_skip(path: str) -> bool:
    """静态资源与日志接口本身不记录，避免刷屏和递归。"""
    return path.startswith(_SKIP_PREFIXES) or path.startswith("/api/logs")


def _body_preview() -> str:
    try:
        if request.files:
            names = ", ".join(sorted(request.files.keys()))
            return f"[file] {names}"
        if request.is_json:
            payload = request.get_json(silent=True)
            return json.dumps(payload, ensure_ascii=False)[:500] if payload else ""
        if request.form:
            return json.dumps(dict(request.form), ensure_ascii=False)[:500]
    except Exception:
        pass
    return ""


def _install_access_log(app: Flask) -> None:
    """记录前端发起的每个接口请求（静态资源与日志接口除外）。"""

    @app.before_request
    def _access_start():
        g._access_started = time.perf_counter()
        g._access_body = "" if _should_skip(request.path) else _body_preview()

    @app.after_request
    def _access_end(resp):
        if _should_skip(request.path):
            return resp
        started = getattr(g, "_access_started", None)
        duration = int((time.perf_counter() - started) * 1000) if started else 0
        try:
            from . import store, trace

            store.add_access_log(
                method=request.method,
                path=request.path,
                query=request.query_string.decode("utf-8", "replace"),
                status=resp.status_code,
                duration_ms=duration,
                ip=request.remote_addr or "",
                body=getattr(g, "_access_body", ""),   # 入库原文，出库统一脱敏
            )
        except Exception:
            pass
        return resp
