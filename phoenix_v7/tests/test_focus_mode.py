import json
import time

from guardrails.focus_mode import is_focus_mode_enabled, set_focus_mode, focus_mode_status_line


def test_is_enabled_missing_file_returns_false(tmp_path):
    path = tmp_path / "focus_mode.json"
    assert is_focus_mode_enabled(path=path) is False


def test_is_enabled_corrupted_json_returns_false(tmp_path):
    path = tmp_path / "focus_mode.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert is_focus_mode_enabled(path=path) is False


def test_set_focus_mode_on_then_is_enabled_true(tmp_path):
    path = tmp_path / "focus_mode.json"
    set_focus_mode(True, path=path)
    assert is_focus_mode_enabled(path=path) is True


def test_set_focus_mode_off_then_is_enabled_false(tmp_path):
    path = tmp_path / "focus_mode.json"
    set_focus_mode(True, path=path)
    set_focus_mode(False, path=path)
    assert is_focus_mode_enabled(path=path) is False


def test_set_focus_mode_records_enabled_at_timestamp(tmp_path):
    path = tmp_path / "focus_mode.json"
    set_focus_mode(True, path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["enabled"] is True
    assert isinstance(data["enabled_at"], str) and data["enabled_at"]


def test_set_focus_mode_off_clears_enabled_at(tmp_path):
    path = tmp_path / "focus_mode.json"
    set_focus_mode(True, path=path)
    set_focus_mode(False, path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["enabled_at"] is None


def test_status_line_when_disabled(tmp_path):
    path = tmp_path / "focus_mode.json"
    assert focus_mode_status_line(path=path) == "关闭"


def test_status_line_when_enabled_shows_duration(tmp_path):
    path = tmp_path / "focus_mode.json"
    set_focus_mode(True, path=path)
    line = focus_mode_status_line(path=path)
    assert line.startswith("开启")
    assert "持续" in line


def test_status_line_corrupted_file_defaults_to_off(tmp_path):
    path = tmp_path / "focus_mode.json"
    path.write_text("not json at all", encoding="utf-8")
    assert focus_mode_status_line(path=path) == "关闭"
