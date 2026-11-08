"""运行时可配置项。

配置统一存在 SQLite 的 settings_kv 表（key = "config"），不再散落到 json 文件。
老版本留下的 data/settings.json 会在首次读取时自动导入并改名归档。

结构：
{
  "fetch":  {"gap_mode": "fixed|random", "gap_ms": 500,
             "gap_min_ms": 300, "gap_max_ms": 1500},
  "renew":  {"enabled": true, "mode": "interval|daily",
             "interval_hours": 24, "daily_time": "03:00", "lifetime": "30d",
             "gap_mode": "random", "gap_ms": 800,
             "gap_min_ms": 500, "gap_max_ms": 2000}
}
"""

import json
import os
import random
from typing import Any, Dict

from . import store
from .config import DATA_DIR, LIFETIME_OPTIONS

KV_KEY = "config"
LEGACY_PATH = DATA_DIR / "settings.json"

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "fetch": {
        "gap_mode": "fixed",
        "gap_ms": 500,
        "gap_min_ms": 300,
        "gap_max_ms": 1500,
    },
    "renew": {
        "enabled": True,
        "mode": "interval",
        "interval_hours": 24,
        "daily_time": "03:00",
        "lifetime": "30d",
        "gap_mode": "random",
        "gap_ms": 800,
        "gap_min_ms": 500,
        "gap_max_ms": 2000,
    },
}


class SettingsError(Exception):
    pass


def _clamp(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _normalize_gap(raw: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    mode = raw.get("gap_mode", base["gap_mode"])
    if mode not in ("fixed", "random"):
        mode = base["gap_mode"]
    gap_ms = _clamp(raw.get("gap_ms"), 0, 60000, base["gap_ms"])
    gap_min = _clamp(raw.get("gap_min_ms"), 0, 60000, base["gap_min_ms"])
    gap_max = _clamp(raw.get("gap_max_ms"), 0, 60000, base["gap_max_ms"])
    if gap_min > gap_max:
        gap_min, gap_max = gap_max, gap_min
    return {
        "gap_mode": mode,
        "gap_ms": gap_ms,
        "gap_min_ms": gap_min,
        "gap_max_ms": gap_max,
    }


def _valid_time(value: str) -> bool:
    parts = str(value).split(":")
    if len(parts) != 2:
        return False
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    fetch_raw = raw.get("fetch") if isinstance(raw.get("fetch"), dict) else {}
    renew_raw = raw.get("renew") if isinstance(raw.get("renew"), dict) else {}

    fetch = _normalize_gap(fetch_raw, DEFAULTS["fetch"])

    renew = _normalize_gap(renew_raw, DEFAULTS["renew"])
    renew["enabled"] = bool(renew_raw.get("enabled", DEFAULTS["renew"]["enabled"]))

    mode = renew_raw.get("mode", DEFAULTS["renew"]["mode"])
    renew["mode"] = mode if mode in ("interval", "daily") else DEFAULTS["renew"]["mode"]

    renew["interval_hours"] = _clamp(
        renew_raw.get("interval_hours"), 1, 720, DEFAULTS["renew"]["interval_hours"]
    )

    daily = str(renew_raw.get("daily_time", DEFAULTS["renew"]["daily_time"]))
    if not _valid_time(daily):
        daily = DEFAULTS["renew"]["daily_time"]
    renew["daily_time"] = daily

    lifetime = str(renew_raw.get("lifetime", DEFAULTS["renew"]["lifetime"]))
    renew["lifetime"] = lifetime if lifetime in LIFETIME_OPTIONS else DEFAULTS["renew"]["lifetime"]

    return {"fetch": fetch, "renew": renew}


def _env_overrides(data: Dict[str, Any]) -> Dict[str, Any]:
    """环境变量优先，便于临时排障。"""
    env = os.environ
    renew = data["renew"]
    if env.get("TEMPMAIL_RENEW_MODE") in ("interval", "daily"):
        renew["mode"] = env["TEMPMAIL_RENEW_MODE"]
    if "TEMPMAIL_RENEW_HOURS" in env:
        renew["interval_hours"] = _clamp(env["TEMPMAIL_RENEW_HOURS"], 1, 720,
                                         renew["interval_hours"])
    if _valid_time(env.get("TEMPMAIL_DAILY_TIME", "")):
        renew["daily_time"] = env["TEMPMAIL_DAILY_TIME"]
    if env.get("TEMPMAIL_RENEW_LIFETIME") in LIFETIME_OPTIONS:
        renew["lifetime"] = env["TEMPMAIL_RENEW_LIFETIME"]
    if env.get("TEMPMAIL_RENEW_ENABLED", "").lower() in ("0", "false", "no"):
        renew["enabled"] = False
    return data


def _migrate_legacy() -> Dict[str, Any]:
    """把老的 settings.json 导入数据库，然后改名归档。"""
    raw: Dict[str, Any] = {}
    if LEGACY_PATH.exists():
        try:
            raw = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        try:
            LEGACY_PATH.replace(LEGACY_PATH.with_suffix(".json.migrated"))
        except OSError:
            pass
    data = _normalize(raw or DEFAULTS)
    store.kv_set(KV_KEY, data)
    return data


def load() -> Dict[str, Any]:
    raw = store.kv_get(KV_KEY)
    if not isinstance(raw, dict) or "fetch" not in raw:
        raw = _migrate_legacy()
    return _env_overrides(_normalize(raw))


def save(patch: Dict[str, Any]) -> Dict[str, Any]:
    """合并保存（只覆盖传入的字段），返回保存后的完整配置。"""
    current = load()
    merged = {
        "fetch": {**current["fetch"], **(patch.get("fetch") or {})},
        "renew": {**current["renew"], **(patch.get("renew") or {})},
    }
    normalized = _normalize(merged)
    store.kv_set(KV_KEY, normalized)
    return _env_overrides(normalized)


def next_gap_ms(kind: str) -> int:
    """按配置算出两个邮箱之间的等待毫秒数。"""
    block = load().get(kind) or DEFAULTS.get(kind) or DEFAULTS["fetch"]
    if block.get("gap_mode") == "random":
        low = int(block.get("gap_min_ms", 0))
        high = int(block.get("gap_max_ms", 0))
        return random.randint(low, max(low, high))
    return int(block.get("gap_ms", 0))


def reset_to_defaults() -> Dict[str, Any]:
    return save({"fetch": DEFAULTS["fetch"], "renew": DEFAULTS["renew"]})
