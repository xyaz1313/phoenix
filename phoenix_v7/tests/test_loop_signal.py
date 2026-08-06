
from phoenix_v7.guardrails import loop_signal

class _FakeGoalState:
    def __init__(self, created_at: float):
        self.created_at = created_at

class _FakeGoalManager:
    def __init__(self, session_id, *, active=False, created_at=0.0):
        self.session_id = session_id
        self._active = active
        self._created_at = created_at

    def is_active(self):
        return self._active

    @property
    def state(self):
        return _FakeGoalState(self._created_at) if self._active else None

def test_is_goal_active_true_when_goal_manager_reports_active(monkeypatch):
    monkeypatch.setattr(
        loop_signal,
        "_get_goal_manager",
        lambda session_id: _FakeGoalManager(session_id, active=True, created_at=123.0),
    )
    assert loop_signal._is_goal_active("sess-1") is True

def test_is_goal_active_false_when_no_goal(monkeypatch):
    monkeypatch.setattr(
        loop_signal,
        "_get_goal_manager",
        lambda session_id: _FakeGoalManager(session_id, active=False),
    )
    assert loop_signal._is_goal_active("sess-2") is False

def test_is_goal_active_false_for_empty_session_id():
    assert loop_signal._is_goal_active("") is False

def test_is_goal_active_false_when_import_raises(monkeypatch):
    def _boom(session_id):
        raise ImportError("hermes_cli.goals not available")

    monkeypatch.setattr(loop_signal, "_get_goal_manager", _boom)
    assert loop_signal._is_goal_active("sess-3") is False

def test_goal_created_at_returns_timestamp_when_active(monkeypatch):
    monkeypatch.setattr(
        loop_signal,
        "_get_goal_manager",
        lambda session_id: _FakeGoalManager(session_id, active=True, created_at=456.0),
    )
    assert loop_signal._goal_created_at("sess-4") == 456.0

def test_goal_created_at_none_when_not_active(monkeypatch):
    monkeypatch.setattr(
        loop_signal,
        "_get_goal_manager",
        lambda session_id: _FakeGoalManager(session_id, active=False),
    )
    assert loop_signal._goal_created_at("sess-5") is None

def test_checklist_not_seeded_initially():
    loop_signal._checklist_seeded_by_session.clear()
    assert loop_signal._is_checklist_seeded("sess-6", 100.0) is False

def test_mark_checklist_seeded_then_query_true():
    loop_signal._checklist_seeded_by_session.clear()
    loop_signal._mark_checklist_seeded("sess-7", 200.0)
    assert loop_signal._is_checklist_seeded("sess-7", 200.0) is True

def test_checklist_seeded_resets_for_new_goal_cycle():
    loop_signal._checklist_seeded_by_session.clear()
    loop_signal._mark_checklist_seeded("sess-8", 300.0)
    # 同一个 session，但换了一个新的 goal（created_at 不同）——不该沿用旧标记
    assert loop_signal._is_checklist_seeded("sess-8", 999.0) is False
