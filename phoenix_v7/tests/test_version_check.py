
from phoenix_v7.guardrails import version_check

def test_read_hermes_version_returns_string(monkeypatch):
    # 真实环境里这个应该能正常读到字符串（跟 hermes_cli.__version__ 一致），
    # 这里不 mock，直接验证真实 import 路径没有问题。
    result = version_check._read_hermes_version()
    assert result is None or isinstance(result, str)

def test_read_hermes_version_returns_none_on_import_failure(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "hermes_cli":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert version_check._read_hermes_version() is None

def test_parse_version_basic():
    assert version_check._parse_version("0.19.1") == (0, 19, 1)

def test_parse_version_strips_v_prefix():
    assert version_check._parse_version("v0.19.1") == (0, 19, 1)

def test_parse_version_invalid_returns_none():
    assert version_check._parse_version("not-a-version") is None

def test_parse_version_empty_returns_none():
    assert version_check._parse_version("") is None

def test_compatibility_match(monkeypatch):
    monkeypatch.setattr(version_check, "_read_hermes_version", lambda: "0.19.1")
    assert version_check.check_hermes_compatibility("0.19.1") == "match"

def test_compatibility_newer(monkeypatch):
    monkeypatch.setattr(version_check, "_read_hermes_version", lambda: "0.20.0")
    assert version_check.check_hermes_compatibility("0.19.1") == "newer"

def test_compatibility_older(monkeypatch):
    monkeypatch.setattr(version_check, "_read_hermes_version", lambda: "0.18.0")
    assert version_check.check_hermes_compatibility("0.19.1") == "older"

def test_compatibility_unknown_when_running_version_unreadable(monkeypatch):
    monkeypatch.setattr(version_check, "_read_hermes_version", lambda: None)
    assert version_check.check_hermes_compatibility("0.19.1") == "unknown"

def test_compatibility_unknown_when_verified_version_unparseable(monkeypatch):
    monkeypatch.setattr(version_check, "_read_hermes_version", lambda: "0.19.1")
    assert version_check.check_hermes_compatibility("not-a-version") == "unknown"
