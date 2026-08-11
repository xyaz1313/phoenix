import json
import time

from guardrails.upgrade_watch import (
    check_version_transition,
    is_in_post_upgrade_window,
    record_upgrade_anomaly,
    upgrade_summary_line,
    format_upgrade_log,
)


def test_first_ever_run_seeds_without_transition(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model:\n  default: x\n", encoding="utf-8")
    result = check_version_transition("0.20.0", path=path, config_path=config_path)
    assert result is None
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["last_known_version"] == "0.20.0"
    assert data["transitions"] == []


def test_same_version_again_no_transition(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model:\n  default: x\n", encoding="utf-8")
    check_version_transition("0.20.0", path=path, config_path=config_path)
    result = check_version_transition("0.20.0", path=path, config_path=config_path)
    assert result is None


def test_version_change_produces_transition_and_backup(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model:\n  default: x\n", encoding="utf-8")
    backup_dir = tmp_path / "config_backups"
    check_version_transition("0.19.1", path=path, config_path=config_path, backup_dir=backup_dir)
    result = check_version_transition(
        "0.20.0", path=path, config_path=config_path, backup_dir=backup_dir,
    )
    assert result is not None
    assert result["from"] == "0.19.1"
    assert result["to"] == "0.20.0"
    assert result["backup_path"] is not None
    assert list(backup_dir.iterdir())  # 至少产生了一个备份文件


def test_backup_skips_gracefully_when_config_missing(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    config_path = tmp_path / "does_not_exist.yaml"
    backup_dir = tmp_path / "config_backups"
    check_version_transition("0.19.1", path=path, config_path=config_path, backup_dir=backup_dir)
    result = check_version_transition(
        "0.20.0", path=path, config_path=config_path, backup_dir=backup_dir,
    )
    assert result is not None
    assert result.get("backup_path") is None


def test_is_in_window_true_right_after_transition(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("x: 1\n", encoding="utf-8")
    check_version_transition("0.19.1", path=path, config_path=config_path)
    check_version_transition("0.20.0", path=path, config_path=config_path)
    assert is_in_post_upgrade_window(path=path) is True


def test_is_in_window_false_when_no_transition_ever(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    assert is_in_post_upgrade_window(path=path) is False


def test_is_in_window_false_after_expiry(tmp_path, monkeypatch):
    path = tmp_path / "upgrade_watch.json"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("x: 1\n", encoding="utf-8")
    check_version_transition("0.19.1", path=path, config_path=config_path)
    check_version_transition("0.20.0", path=path, config_path=config_path)
    assert is_in_post_upgrade_window(path=path, window_minutes=0) is False


def test_record_anomaly_inside_window_appends(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("x: 1\n", encoding="utf-8")
    check_version_transition("0.19.1", path=path, config_path=config_path)
    check_version_transition("0.20.0", path=path, config_path=config_path)
    record_upgrade_anomaly("api_error", "rate_limit", path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["transitions"][-1]["anomalies"] == [
        {"kind": "api_error", "detail": "rate_limit", "at": data["transitions"][-1]["anomalies"][0]["at"]}
    ]


def test_record_anomaly_outside_window_noop(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    record_upgrade_anomaly("api_error", "rate_limit", path=path)
    assert not path.exists()


def test_summary_line_no_history(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    assert upgrade_summary_line(path=path) == "无最近版本变化"


def test_summary_line_with_transition(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("x: 1\n", encoding="utf-8")
    check_version_transition("0.19.1", path=path, config_path=config_path)
    check_version_transition("0.20.0", path=path, config_path=config_path)
    line = upgrade_summary_line(path=path)
    assert "0.19.1" in line and "0.20.0" in line


def test_format_upgrade_log_no_history(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    assert "没有" in format_upgrade_log(path=path) or "无" in format_upgrade_log(path=path)


def test_format_upgrade_log_with_anomalies(tmp_path):
    path = tmp_path / "upgrade_watch.json"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("x: 1\n", encoding="utf-8")
    check_version_transition("0.19.1", path=path, config_path=config_path)
    check_version_transition("0.20.0", path=path, config_path=config_path)
    record_upgrade_anomaly("tool_error", "write_file: disk full", path=path)
    log = format_upgrade_log(path=path)
    assert "0.19.1" in log and "0.20.0" in log and "write_file" in log
