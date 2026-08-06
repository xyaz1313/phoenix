
import phoenix_v7

def test_on_approval_response_records_matching_pattern_key(monkeypatch):
    calls = []
    monkeypatch.setattr(
        phoenix_v7, "record_approval_outcome",
        lambda bucket_key, choice: calls.append((bucket_key, choice)),
    )
    phoenix_v7._on_approval_response(
        pattern_key="plugin_rule:phoenix_v7_high_tier:write_file",
        choice="once",
    )
    assert calls == [("write_file", "once")]

def test_on_approval_response_ignores_unrelated_pattern_key(monkeypatch):
    calls = []
    monkeypatch.setattr(
        phoenix_v7, "record_approval_outcome",
        lambda bucket_key, choice: calls.append((bucket_key, choice)),
    )
    phoenix_v7._on_approval_response(
        pattern_key="some_other_dangerous_command_pattern",
        choice="once",
    )
    assert calls == []

def test_on_approval_response_handles_missing_pattern_key(monkeypatch):
    calls = []
    monkeypatch.setattr(
        phoenix_v7, "record_approval_outcome",
        lambda bucket_key, choice: calls.append((bucket_key, choice)),
    )
    phoenix_v7._on_approval_response(choice="once")
    assert calls == []

def test_on_approval_response_extracts_correct_bucket_for_terminal(monkeypatch):
    calls = []
    monkeypatch.setattr(
        phoenix_v7, "record_approval_outcome",
        lambda bucket_key, choice: calls.append((bucket_key, choice)),
    )
    phoenix_v7._on_approval_response(
        pattern_key="plugin_rule:phoenix_v7_high_tier:terminal",
        choice="deny",
    )
    assert calls == [("terminal", "deny")]
