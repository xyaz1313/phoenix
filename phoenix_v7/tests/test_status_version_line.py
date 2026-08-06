import sys

import phoenix_v7

def test_hermes_version_line_match(monkeypatch, capsys):
    monkeypatch.setattr(phoenix_v7, "_read_hermes_version", lambda: "0.19.1")
    monkeypatch.setattr(phoenix_v7, "_read_verified_hermes_version", lambda: "0.19.1")
    monkeypatch.setattr(phoenix_v7, "check_hermes_compatibility", lambda v: "match")
    phoenix_v7._handle_status_cli(None)
    out = capsys.readouterr().out
    assert "Hermes 版本: v0.19.1（已验证）" in out

def test_hermes_version_line_newer(monkeypatch, capsys):
    monkeypatch.setattr(phoenix_v7, "_read_hermes_version", lambda: "0.20.0")
    monkeypatch.setattr(phoenix_v7, "_read_verified_hermes_version", lambda: "0.19.1")
    monkeypatch.setattr(phoenix_v7, "check_hermes_compatibility", lambda v: "newer")
    phoenix_v7._handle_status_cli(None)
    out = capsys.readouterr().out
    assert "比不死鸟验证过的 v0.19.1 新，建议核实一遍兼容性" in out

def test_hermes_version_line_older(monkeypatch, capsys):
    monkeypatch.setattr(phoenix_v7, "_read_hermes_version", lambda: "0.18.0")
    monkeypatch.setattr(phoenix_v7, "_read_verified_hermes_version", lambda: "0.19.1")
    monkeypatch.setattr(phoenix_v7, "check_hermes_compatibility", lambda v: "older")
    phoenix_v7._handle_status_cli(None)
    out = capsys.readouterr().out
    assert "比不死鸟验证过的 v0.19.1 旧，未测试过，可能有问题" in out

def test_hermes_version_line_unknown(monkeypatch, capsys):
    monkeypatch.setattr(phoenix_v7, "_read_hermes_version", lambda: None)
    monkeypatch.setattr(phoenix_v7, "_read_verified_hermes_version", lambda: "0.19.1")
    monkeypatch.setattr(phoenix_v7, "check_hermes_compatibility", lambda v: "unknown")
    phoenix_v7._handle_status_cli(None)
    out = capsys.readouterr().out
    assert "Hermes 版本: 无法读取（不影响不死鸟其它功能）" in out
