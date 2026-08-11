"""专注模式——用户开着的时候，深度/真神档的高危操作确认提示直接跳过，方便
固定用一个模型专心干活时不被打断。跟审批信任机制（approval_trust.py）并列
处理，两者都拦不住 hardline 永久高危命令类别——那条安全红线谁也不能覆盖。

状态持久化在 phoenix_v7_state/focus_mode.json，重启 Hermes 不失效，不做
自动到期（怕干活干到一半提示突然又弹回来，比一直弹更让人困惑）。"""
from __future__ import annotations

import json
import time
from pathlib import Path


def _default_path() -> Path:
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "phoenix_v7_state" / "focus_mode.json"


def _load(path: Path | None) -> dict:
    target = path or _default_path()
    if not target.exists():
        return {"enabled": False, "enabled_at": None}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False, "enabled_at": None}
    if not isinstance(data, dict):
        return {"enabled": False, "enabled_at": None}
    return {
        "enabled": bool(data.get("enabled", False)),
        "enabled_at": data.get("enabled_at"),
    }


def is_focus_mode_enabled(path: Path | None = None) -> bool:
    return _load(path)["enabled"]


def set_focus_mode(enabled: bool, path: Path | None = None) -> None:
    target = path or _default_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "enabled": enabled,
        "enabled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) if enabled else None,
    }
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def focus_mode_status_line(path: Path | None = None) -> str:
    data = _load(path)
    if not data["enabled"]:
        return "关闭"
    enabled_at = data.get("enabled_at")
    if not isinstance(enabled_at, str) or not enabled_at:
        return "开启"
    try:
        started = time.strptime(enabled_at, "%Y-%m-%dT%H:%M:%SZ")
        started_epoch = time.mktime(started) - time.timezone
        elapsed = max(0, int(time.time() - started_epoch))
    except Exception:
        return "开启"
    hours, remainder = divmod(elapsed, 3600)
    minutes = remainder // 60
    return f"开启（已持续{hours}小时{minutes}分钟）"
