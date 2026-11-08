"""OneTimeEmail 站点客户端。

站点协议要点（通过抓包确认）：
1. GET  {prefix}/            返回页面内含 <meta name="csrf-token">，并下发 PHPSESSID
2. POST {prefix}/create_inbox.php   需要 Cookie + X-CSRF-Token，返回 email/uuid/recovery_phrase
3. POST {prefix}/api/api_update_lifetime.php  表单 uuid + lifetime，用于设置/续期
4. GET  {prefix}/api/api_check_emails.php?uuid=  读取邮件列表与正文
5. POST {prefix}/api/api_delete_inbox.php        删除（表单 uuid）
"""

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .. import trace
from ..config import (
    DEFAULT_LIFETIME,
    HTTP_TIMEOUT,
    LIFETIME_OPTIONS,
    SITE_BASE,
    SITE_PREFIX,
    USER_AGENT,
)

_CSRF_META = re.compile(r'name="csrf-token"\s+content="([^"]+)"')
_CSRF_INPUT = re.compile(r'name="csrf_token"\s+value="([^"]+)"')


class SiteError(Exception):
    """调用站点接口失败。"""


class OneTimeEmailClient:
    def __init__(self, cookies: str = ""):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"{SITE_BASE}{SITE_PREFIX}/",
        })
        if cookies:
            self.load_cookies(cookies)

    # ---------------- cookie 序列化 ----------------
    @property
    def cookies(self) -> str:
        return "; ".join(f"{c.name}={c.value}" for c in self.session.cookies)

    def load_cookies(self, raw: str) -> None:
        for chunk in str(raw or "").split(";"):
            if "=" not in chunk:
                continue
            name, _, value = chunk.partition("=")
            name, value = name.strip(), value.strip()
            if name and value:
                self.session.cookies.set(name, value, domain="onetimeemail.com")

    # ---------------- 基础请求 ----------------
    def _url(self, path: str) -> str:
        return f"{SITE_BASE}{SITE_PREFIX}{path}" if path.startswith("/") else \
               f"{SITE_BASE}{SITE_PREFIX}/{path}"

    def _get(self, path: str, **kwargs) -> requests.Response:
        url = self._url(path)
        started = time.perf_counter()
        try:
            resp = self.session.get(url, timeout=HTTP_TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            trace.record_http("GET", url, 0, self._elapsed(started), error=str(exc))
            raise SiteError(f"网络请求失败: {exc}") from exc
        trace.record_http("GET", url, resp.status_code, self._elapsed(started),
                          response_body=self._snippet(resp), sanitize_on_write=False)
        return resp

    def _post(self, path: str, data: Optional[Dict[str, Any]] = None,
              headers: Optional[Dict[str, str]] = None) -> requests.Response:
        url = self._url(path)
        started = time.perf_counter()
        try:
            resp = self.session.post(url, data=data, headers=headers,
                                     timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:
            trace.record_http("POST", url, 0, self._elapsed(started),
                              request_body=str(data or ""), error=str(exc),
                              sanitize_on_write=False)
            raise SiteError(f"网络请求失败: {exc}") from exc
        trace.record_http("POST", url, resp.status_code, self._elapsed(started),
                          request_body=str(data or ""),
                          response_body=self._snippet(resp), sanitize_on_write=False)
        return resp

    @staticmethod
    def _elapsed(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    @staticmethod
    def _snippet(resp: requests.Response, limit: int = 4000) -> str:
        try:
            return resp.text[:limit]
        except Exception:
            return ""

    @staticmethod
    def _json(resp: requests.Response) -> Dict[str, Any]:
        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError):
            snippet = resp.text[:160].replace("\n", " ")
            raise SiteError(f"站点返回非 JSON（HTTP {resp.status_code}）: {snippet}")
        if not isinstance(data, dict):
            raise SiteError("站点返回数据格式异常。")
        return data

    # ---------------- CSRF ----------------
    def fetch_csrf(self) -> str:
        resp = self._get("/")
        if resp.status_code != 200:
            raise SiteError(f"打开站点失败（HTTP {resp.status_code}）。")
        html = resp.text
        match = _CSRF_META.search(html) or _CSRF_INPUT.search(html)
        if not match:
            raise SiteError("页面中未找到 CSRF token，站点结构可能已变更。")
        return match.group(1)

    def _csrf_headers(self, token: str) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": token,
            "Origin": SITE_BASE,
            "Referer": f"{SITE_BASE}{SITE_PREFIX}/",
        }

    # ---------------- 创建 ----------------
    def create_inbox(self, auto_set_lifetime: str = DEFAULT_LIFETIME
                     ) -> Tuple[Dict[str, Any], str]:
        """创建收件箱，返回 (创建结果, cookie 字符串)。"""
        token = self.fetch_csrf()  # 同时拿到 PHPSESSID
        resp = self._post("/create_inbox.php", headers=self._csrf_headers(token))

        # 403 表示 CSRF 过期，按官方前端逻辑重新取一次表单
        if resp.status_code == 403:
            token = self.fetch_csrf()
            resp = self._post("/create_inbox.php", headers=self._csrf_headers(token))

        data = self._json(resp)
        if not data.get("success") or not data.get("uuid"):
            raise SiteError(data.get("error") or "创建临时邮箱失败。")

        uuid = data["uuid"]
        # 站点默认给 1h，需要显式改成 30 天
        if auto_set_lifetime and auto_set_lifetime != data.get("lifetime"):
            try:
                self.update_lifetime(uuid, auto_set_lifetime)
                data["lifetime"] = auto_set_lifetime
            except SiteError:
                pass
        return data, self.cookies

    # ---------------- 续期 ----------------
    def update_lifetime(self, uuid: str, lifetime: str = DEFAULT_LIFETIME) -> None:
        if lifetime not in LIFETIME_OPTIONS:
            raise SiteError(f"不支持的有效期：{lifetime}")
        resp = self._post("/api/api_update_lifetime.php",
                          data={"uuid": uuid, "lifetime": lifetime})
        if resp.status_code != 200:
            raise SiteError(f"续期失败：收件箱不可用（HTTP {resp.status_code}）。")
        data = self._json(resp)
        if not data.get("success"):
            raise SiteError(data.get("error") or "续期失败。")

    # ---------------- 收信 ----------------
    def check_emails(self, uuid: str) -> Dict[str, Any]:
        resp = self._get(f"/api/api_check_emails.php?uuid={uuid}")
        # 邮箱被删除或过期时站点直接返回 403 HTML 页面，而非 JSON
        if resp.status_code != 200:
            raise SiteError("收件箱不可用或已过期（可能已被删除，或超过 30 天未访问）。")
        data = self._json(resp)
        if not data.get("success"):
            raise SiteError(data.get("error") or "收件箱不可用或已过期。")
        data.setdefault("emails", [])
        return data

    def delete_inbox(self, uuid: str) -> bool:
        resp = self._post("/api/api_delete_inbox.php", data={"uuid": uuid})
        try:
            data = self._json(resp)
        except SiteError:
            return False
        return bool(data.get("success"))


def normalize_emails(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """统一邮件字段名，屏蔽站点字段变动。"""
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        out.append({
            "id": item.get("id") or item.get("mail_id") or "",
            "sender": item.get("sender") or item.get("from") or "",
            "subject": item.get("subject") or "",
            "received_at": item.get("received_at") or item.get("date") or "",
            "body_html": item.get("body_html") or "",
            "body_text": item.get("body_text") or item.get("body") or "",
        })
    return out
