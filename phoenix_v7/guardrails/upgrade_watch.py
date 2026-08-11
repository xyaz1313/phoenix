"""升级安全网——新session开始时检测Hermes版本是否变化（=两次会话之间发生过
一次升级），变化时备份config.yaml、记一条transition，30分钟窗口内的工具/API
错误自动归档到这次transition下，供用户回头查"升级后到底出了什么问题"。

只备份 config.yaml，不备份整个 ~/.hermes（memories/skills/sessions太大，
也不是不死鸟的地盘）。不做自动诊断，只归档现象文本。"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

_WINDOW_MINUTES_DEFAULT = 30


def _default_state_path() -> Path:
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "phoenix_v7_state" / "upgrade_watch.json"


def _default_config_path() -> Path:
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "config.yaml"


def _default_backup_dir() -> Path:
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "phoenix_v7_state" / "config_backups"


def _load(path: Path) -> dict:
    if not path.exists():
        return {"last_known_version": None, "window_started_at": None, "transitions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"last_known_version": None, "window_started_at": None, "transitions": []}
    if not isinstance(data, dict):
        return {"last_known_version": None, "window_started_at": None, "transitions": []}
    data.setdefault("last_known_version", None)
    data.setdefault("window_started_at", None)
    data.setdefault("transitions", [])
    return data


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def check_version_transition(
    current_version: str | None,
    path: Path | None = None,
    config_path: Path | None = None,
    backup_dir: Path | None = None,
) -> dict | None:
    if not current_version:
        return None
    target = path or _default_state_path()
    data = _load(target)
    previous = data["last_known_version"]
    if previous is None:
        data["last_known_version"] = current_version
        _save(target, data)
        return None
    if previous == current_version:
        return None

    backup_path = None
    cfg = config_path or _default_config_path()
    if cfg.exists():
        dest_dir = backup_dir or _default_backup_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d%H%M%S", time.gmtime())
        dest = dest_dir / f"config.yaml.{previous}-to-{current_version}.{ts}.bak"
        try:
            shutil.copy2(cfg, dest)
            backup_path = str(dest)
        except Exception:
            backup_path = None

    transition = {
        "from": previous, "to": current_version, "detected_at": _now(),
        "backup_path": backup_path, "anomalies": [],
    }
    data["transitions"].append(transition)
    data["last_known_version"] = current_version
    data["window_started_at"] = _now()
    _save(target, data)
    return transition


def is_in_post_upgrade_window(
    path: Path | None = None, window_minutes: int = _WINDOW_MINUTES_DEFAULT,
) -> bool:
    target = path or _default_state_path()
    data = _load(target)
    started = data.get("window_started_at")
    if not started:
        return False
    try:
        started_struct = time.strptime(started, "%Y-%m-%dT%H:%M:%SZ")
        started_epoch = time.mktime(started_struct) - time.timezone
    except Exception:
        return False
    elapsed_minutes = (time.time() - started_epoch) / 60
    return 0 <= elapsed_minutes <= window_minutes


def record_upgrade_anomaly(kind: str, detail: str, path: Path | None = None) -> None:
    target = path or _default_state_path()
    if not is_in_post_upgrade_window(path=target):
        return
    data = _load(target)
    if not data["transitions"]:
        return
    data["transitions"][-1]["anomalies"].append(
        {"kind": kind, "detail": detail, "at": _now()}
    )
    _save(target, data)


def upgrade_summary_line(path: Path | None = None) -> str:
    target = path or _default_state_path()
    data = _load(target)
    if not data["transitions"]:
        return "无最近版本变化"
    last = data["transitions"][-1]
    count = len(last["anomalies"])
    detected = last["detected_at"].split("T")[0]
    if count:
        return f"v{last['from']}→v{last['to']}（{detected}），检测到{count}条可能相关异常"
    return f"v{last['from']}→v{last['to']}（{detected}），暂无相关异常"


def format_upgrade_log(path: Path | None = None) -> str:
    target = path or _default_state_path()
    data = _load(target)
    if not data["transitions"]:
        return "没有版本变化记录"
    lines = ["phoenix_v7 升级历史："]
    for t in data["transitions"]:
        lines.append(f"  v{t['from']} → v{t['to']}（{t['detected_at']}）")
        if t.get("backup_path"):
            lines.append(f"    config.yaml 备份: {t['backup_path']}")
        for a in t["anomalies"]:
            lines.append(f"    [{a['kind']}] {a['detail']}（{a['at']}）")
    return "\n".join(lines)
