from types import SimpleNamespace

import phoenix_v7


def _reset_state():
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._current_provider_by_session.clear()
    phoenix_v7._privacy_flagged_by_session.clear()
    phoenix_v7._privacy_warned_sessions.clear()
    phoenix_v7._checkpoint_reminder_warned_sessions.clear()


def _fake_client(content: str):
    def create(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_record_api_error_sends_alert_when_breaker_trips(monkeypatch):
    calls = []
    monkeypatch.setattr(
        phoenix_v7, "send_alert",
        lambda event, session_id, detail: calls.append((event, session_id, detail)),
    )
    phoenix_v7._breaker.record_success()  # 复位，确保从 closed 状态开始
    phoenix_v7._record_api_error(session_id="s-trip", error={"type": "rate_limit"})
    phoenix_v7._record_api_error(session_id="s-trip", error={"type": "rate_limit"})
    assert calls == []  # 阈值是3，前两次失败不该报警
    phoenix_v7._record_api_error(session_id="s-trip", error={"type": "rate_limit"})
    assert len(calls) == 1
    assert calls[0][0] == "circuit_breaker_tripped"
    assert calls[0][1] == "s-trip"


def test_record_api_error_does_not_resend_while_already_open(monkeypatch):
    calls = []
    monkeypatch.setattr(
        phoenix_v7, "send_alert",
        lambda event, session_id, detail: calls.append((event, session_id, detail)),
    )
    phoenix_v7._breaker.record_success()
    for _ in range(3):
        phoenix_v7._record_api_error(session_id="s-trip-2", error={"type": "rate_limit"})
    assert len(calls) == 1
    phoenix_v7._record_api_error(session_id="s-trip-2", error={"type": "rate_limit"})
    assert len(calls) == 1  # 已经是open状态，第4次失败不重复报警


def test_guard_tool_sends_alert_on_hardline_command(monkeypatch):
    calls = []
    monkeypatch.setattr(
        phoenix_v7, "send_alert",
        lambda event, session_id, detail: calls.append((event, session_id, detail)),
    )
    monkeypatch.setattr(phoenix_v7, "is_checkpoints_enabled", lambda: True)
    _reset_state()
    phoenix_v7._guard_tool("terminal", {"command": "rm -rf /"}, session_id="s-hardline")
    assert len(calls) == 1
    assert calls[0][0] == "hardline_command_detected"
    assert calls[0][1] == "s-hardline"


def test_guard_tool_benign_command_does_not_send_alert(monkeypatch):
    calls = []
    monkeypatch.setattr(
        phoenix_v7, "send_alert",
        lambda event, session_id, detail: calls.append((event, session_id, detail)),
    )
    monkeypatch.setattr(phoenix_v7, "is_checkpoints_enabled", lambda: True)
    _reset_state()
    phoenix_v7._guard_tool("terminal", {"command": "ls -la"}, session_id="s-benign")
    assert calls == []


def test_transform_output_sends_alert_on_privacy_warning(monkeypatch):
    calls = []
    monkeypatch.setattr(
        phoenix_v7, "send_alert",
        lambda event, session_id, detail: calls.append((event, session_id, detail)),
    )
    _reset_state()
    phoenix_v7._last_tier_by_session["s-privacy"] = "l1_daily"
    phoenix_v7._privacy_flagged_by_session["s-privacy"] = True
    phoenix_v7._current_provider_by_session["s-privacy"] = "nous"
    phoenix_v7._transform_output(
        response_text="这是模型的真实回复内容", session_id="s-privacy", model="z-ai/glm-5.2",
    )
    events = [c[0] for c in calls]
    assert "privacy_warning_triggered" in events


def test_transform_output_sends_alert_on_hallucination_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(
        phoenix_v7, "send_alert",
        lambda event, session_id, detail: calls.append((event, session_id, detail)),
    )
    _reset_state()
    phoenix_v7._last_tier_by_session["s-halluc"] = "l3_critical"
    phoenix_v7._privacy_flagged_by_session["s-halluc"] = False
    phoenix_v7._current_provider_by_session["s-halluc"] = "nous"

    def fake_get_client(task=None):
        return _fake_client("ISSUE: 这里的数字看起来是编造的"), "verifier-model"

    monkeypatch.setattr(phoenix_v7, "get_text_auxiliary_client", fake_get_client)
    phoenix_v7._transform_output(
        response_text="这是模型的真实回复内容", session_id="s-halluc", model="z-ai/glm-5.2",
    )
    events = [c[0] for c in calls]
    assert "hallucination_flagged" in events


def test_transform_output_no_issues_does_not_send_alert(monkeypatch):
    calls = []
    monkeypatch.setattr(
        phoenix_v7, "send_alert",
        lambda event, session_id, detail: calls.append((event, session_id, detail)),
    )
    _reset_state()
    phoenix_v7._last_tier_by_session["s-clean"] = "l1_daily"
    phoenix_v7._privacy_flagged_by_session["s-clean"] = False
    phoenix_v7._current_provider_by_session["s-clean"] = "nous"
    phoenix_v7._transform_output(response_text="正常回复", session_id="s-clean", model="z-ai/glm-5.2")
    assert calls == []
