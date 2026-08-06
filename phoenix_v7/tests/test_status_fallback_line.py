import sys

import phoenix_v7

def test_load_fallback_chain_reads_list(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "fallback_model:\n"
        "  - provider: turbofieldfare\n"
        "    model: gemma-4-26b-a4b-it\n"
        "  - provider: nous\n"
        "    model: stepfun/step-3.7-flash:free\n",
        encoding="utf-8",
    )
    chain = phoenix_v7._load_fallback_chain(path=config_path)
    assert chain == [
        {"provider": "turbofieldfare", "model": "gemma-4-26b-a4b-it"},
        {"provider": "nous", "model": "stepfun/step-3.7-flash:free"},
    ]

def test_load_fallback_chain_reads_single_dict(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "fallback_model:\n  provider: nous\n  model: anthropic/claude-sonnet-4\n",
        encoding="utf-8",
    )
    chain = phoenix_v7._load_fallback_chain(path=config_path)
    assert chain == [{"provider": "nous", "model": "anthropic/claude-sonnet-4"}]

def test_load_fallback_chain_missing_key_returns_empty(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model:\n  provider: nous\n", encoding="utf-8")
    assert phoenix_v7._load_fallback_chain(path=config_path) == []

def test_load_fallback_chain_missing_file_returns_empty(tmp_path):
    assert phoenix_v7._load_fallback_chain(path=tmp_path / "nope.yaml") == []

def test_load_fallback_chain_malformed_yaml_returns_empty(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("not: valid: yaml: [", encoding="utf-8")
    assert phoenix_v7._load_fallback_chain(path=config_path) == []

def test_status_cli_shows_fallback_chain(monkeypatch, capsys):
    monkeypatch.setattr(
        phoenix_v7,
        "_load_fallback_chain",
        lambda: [
            {"provider": "turbofieldfare", "model": "gemma-4-26b-a4b-it"},
            {"provider": "nous", "model": "stepfun/step-3.7-flash:free"},
        ],
    )
    phoenix_v7._handle_status_cli(None)
    out = capsys.readouterr().out
    assert "欠费兜底链" in out
    assert "turbofieldfare/gemma-4-26b-a4b-it" in out
    assert "nous/stepfun/step-3.7-flash:free" in out

def test_status_cli_shows_unconfigured_when_empty(monkeypatch, capsys):
    monkeypatch.setattr(phoenix_v7, "_load_fallback_chain", lambda: [])
    phoenix_v7._handle_status_cli(None)
    out = capsys.readouterr().out
    assert "欠费兜底链: 未配置" in out
