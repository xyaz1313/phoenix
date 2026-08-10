
import phoenix_v7

def test_guard_tool_flags_checkpoint_reminder_when_destructive_and_disabled(monkeypatch):
    # 新行为（事前拦截）：checkpoints 未开 + 高危调用 -> _guard_tool 直接返回
    # approve 指令并附带提醒文字，不再是"设 pending 标记，等回复生成完事后追加"。
    monkeypatch.setattr(phoenix_v7, "is_checkpoints_enabled", lambda: False)
    phoenix_v7._checkpoint_reminder_warned_sessions.discard("ckpt-1")
    result = phoenix_v7._guard_tool("write_file", {"path": "/tmp/x.py"}, session_id="ckpt-1")
    assert result is not None
    assert result["action"] == "approve"
    assert result["rule_key"] == "phoenix_v7_checkpoint_reminder"
    assert "即将执行高危操作" in result["message"]

def test_guard_tool_does_not_flag_when_checkpoints_already_enabled(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "is_checkpoints_enabled", lambda: True)
    phoenix_v7._checkpoint_reminder_warned_sessions.discard("ckpt-2")
    result = phoenix_v7._guard_tool("write_file", {"path": "/tmp/x.py"}, session_id="ckpt-2")
    assert result is None or result.get("rule_key") != "phoenix_v7_checkpoint_reminder"

def test_guard_tool_does_not_flag_for_non_destructive_call(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "is_checkpoints_enabled", lambda: False)
    phoenix_v7._checkpoint_reminder_warned_sessions.discard("ckpt-3")
    result = phoenix_v7._guard_tool("terminal", {"command": "ls -la"}, session_id="ckpt-3")
    assert result is None or result.get("rule_key") != "phoenix_v7_checkpoint_reminder"

def test_guard_tool_checkpoint_reminder_only_fires_once_per_session(monkeypatch):
    # 同一 session 里，第二次高危调用不该重复提醒（用 _checkpoint_reminder_warned_sessions
    # 记住已经提醒过），否则每次写文件都刷一遍提醒文字，噪音太大。
    monkeypatch.setattr(phoenix_v7, "is_checkpoints_enabled", lambda: False)
    phoenix_v7._checkpoint_reminder_warned_sessions.discard("ckpt-4")
    first = phoenix_v7._guard_tool("write_file", {"path": "/tmp/x.py"}, session_id="ckpt-4")
    assert first is not None and first.get("rule_key") == "phoenix_v7_checkpoint_reminder"
    second = phoenix_v7._guard_tool("write_file", {"path": "/tmp/y.py"}, session_id="ckpt-4")
    assert second is None or second.get("rule_key") != "phoenix_v7_checkpoint_reminder"

def _patch_goal(monkeypatch, *, active: bool, created_at: float = 100.0, seeded: bool = False):
    monkeypatch.setattr(phoenix_v7, "_is_goal_active", lambda session_id: active)
    monkeypatch.setattr(phoenix_v7, "_goal_created_at", lambda session_id: created_at if active else None)
    monkeypatch.setattr(phoenix_v7, "_is_checklist_seeded", lambda session_id, goal_created_at: seeded)

def test_guard_tool_blocks_non_whitelisted_tool_when_loop_active_unseeded(monkeypatch):
    _patch_goal(monkeypatch, active=True, seeded=False)
    result = phoenix_v7._guard_tool("terminal", {}, session_id="sess-loop-1")
    assert result["rule_key"] == "phoenix_v7_loop_checklist_required"

def test_guard_tool_allows_todo_and_marks_seeded(monkeypatch):
    _patch_goal(monkeypatch, active=True, created_at=100.0, seeded=False)
    seeded_calls = []
    monkeypatch.setattr(
        phoenix_v7, "_mark_checklist_seeded",
        lambda session_id, goal_created_at: seeded_calls.append((session_id, goal_created_at)),
    )
    result = phoenix_v7._guard_tool("todo", {"todos": []}, session_id="sess-loop-2")
    assert result is None
    assert seeded_calls == [("sess-loop-2", 100.0)]

def test_guard_tool_no_active_loop_unaffected(monkeypatch):
    _patch_goal(monkeypatch, active=False)
    phoenix_v7._last_tier_by_session["sess-no-loop"] = "l1_daily"
    result = phoenix_v7._guard_tool("terminal", {}, session_id="sess-no-loop")
    assert result is None

def test_guard_tool_loop_active_seeded_high_tier_blocks_for_evaluator(monkeypatch):
    _patch_goal(monkeypatch, active=True, seeded=True)
    phoenix_v7._last_tier_by_session["sess-loop-3"] = "l3_critical"
    result = phoenix_v7._guard_tool("terminal", {}, session_id="sess-loop-3")
    assert result["rule_key"] == "phoenix_v7_loop_high_tier_needs_evaluator"

def test_subagent_stop_records_approval_on_approved_summary():
    phoenix_v7._pending_loop_approvals.clear()
    phoenix_v7._on_subagent_stop(
        parent_session_id="sess-eval-1",
        child_summary="APPROVED: 这个操作看起来是安全的，可以执行",
        child_status="completed",
    )
    assert phoenix_v7._pending_loop_approvals.get("sess-eval-1") is True

def test_subagent_stop_case_insensitive_approved_prefix():
    phoenix_v7._pending_loop_approvals.clear()
    phoenix_v7._on_subagent_stop(
        parent_session_id="sess-eval-2",
        child_summary="approved, looks fine",
        child_status="completed",
    )
    assert phoenix_v7._pending_loop_approvals.get("sess-eval-2") is True

def test_subagent_stop_rejected_summary_does_not_record_approval():
    phoenix_v7._pending_loop_approvals.clear()
    phoenix_v7._on_subagent_stop(
        parent_session_id="sess-eval-3",
        child_summary="REJECTED: 这个操作风险太高，不应该执行",
        child_status="completed",
    )
    assert "sess-eval-3" not in phoenix_v7._pending_loop_approvals

def test_subagent_stop_missing_parent_session_id_is_noop():
    phoenix_v7._pending_loop_approvals.clear()
    phoenix_v7._on_subagent_stop(parent_session_id="", child_summary="APPROVED", child_status="completed")
    assert phoenix_v7._pending_loop_approvals == {}

def test_guard_tool_consumes_pending_approval_and_allows_once(monkeypatch):
    _patch_goal(monkeypatch, active=True, seeded=True)
    phoenix_v7._last_tier_by_session["sess-eval-4"] = "l3_critical"
    phoenix_v7._pending_loop_approvals["sess-eval-4"] = True

    first = phoenix_v7._guard_tool("terminal", {}, session_id="sess-eval-4")
    assert first is None  # 批准被消费，第一次放行

    second = phoenix_v7._guard_tool("terminal", {}, session_id="sess-eval-4")
    assert second["rule_key"] == "phoenix_v7_loop_high_tier_needs_evaluator"  # 批准已用掉，第二次照样拦

def test_guard_tool_high_tier_todo_call_does_not_mark_seeded_until_allowed(monkeypatch):
    _patch_goal(monkeypatch, active=True, created_at=100.0, seeded=False)
    seeded_calls = []
    monkeypatch.setattr(
        phoenix_v7, "_mark_checklist_seeded",
        lambda session_id, goal_created_at: seeded_calls.append((session_id, goal_created_at)),
    )
    phoenix_v7._last_tier_by_session["sess-high-todo"] = "l3_critical"
    phoenix_v7._pending_loop_approvals.pop("sess-high-todo", None)

    blocked = phoenix_v7._guard_tool("todo", {"todos": []}, session_id="sess-high-todo")
    assert blocked["rule_key"] == "phoenix_v7_loop_high_tier_needs_evaluator"
    assert seeded_calls == []

    phoenix_v7._pending_loop_approvals["sess-high-todo"] = True
    allowed = phoenix_v7._guard_tool("todo", {"todos": []}, session_id="sess-high-todo")
    assert allowed is None
    assert seeded_calls == [("sess-high-todo", 100.0)]

def test_guard_tool_passes_trusted_true_when_bucket_trusted(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "is_approval_trusted", lambda bucket_key: True)
    monkeypatch.setattr(phoenix_v7, "is_checkpoints_enabled", lambda: True)  # 避免存档点提醒干扰
    monkeypatch.setattr(phoenix_v7, "_last_tier_by_session", {"trust-1": "l2_deep"})
    result = phoenix_v7._guard_tool("write_file", {"path": "/tmp/x.py"}, session_id="trust-1")
    assert result is None  # 信任够了，不该再触发确认

def test_guard_tool_passes_trusted_false_when_bucket_not_trusted(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "is_approval_trusted", lambda bucket_key: False)
    monkeypatch.setattr(phoenix_v7, "_last_tier_by_session", {"trust-2": "l2_deep"})
    result = phoenix_v7._guard_tool("write_file", {"path": "/tmp/x.py"}, session_id="trust-2")
    assert result is not None
    assert result["action"] == "approve"

def test_guard_tool_detects_hardline_terminal_command(monkeypatch):
    # 即使信任已经攒够，命中永久高危命令类别时也不能跳过——这条走真实的
    # tools.approval.detect_hardline_command()，用一个真实会被判定为hardline
    # 的命令（清空根目录）而不是mock，验证import路径和真实判断逻辑本身可用。
    monkeypatch.setattr(phoenix_v7, "is_approval_trusted", lambda bucket_key: True)
    monkeypatch.setattr(phoenix_v7, "_last_tier_by_session", {"trust-3": "l3_critical"})
    result = phoenix_v7._guard_tool(
        "terminal", {"command": "rm -rf /"}, session_id="trust-3",
    )
    assert result is not None
    assert result["action"] == "approve"

def test_guard_tool_benign_command_not_treated_as_hardline(monkeypatch):
    monkeypatch.setattr(phoenix_v7, "is_approval_trusted", lambda bucket_key: True)
    monkeypatch.setattr(phoenix_v7, "_last_tier_by_session", {"trust-4": "l2_deep"})
    result = phoenix_v7._guard_tool(
        "terminal", {"command": "ls -la"}, session_id="trust-4",
    )
    assert result is None  # 信任够了、命令本身不是hardline，应该放行

def test_subagent_start_inherits_parent_tier():
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._last_tier_by_session["parent-1"] = "l3_critical"
    phoenix_v7._on_subagent_start(parent_session_id="parent-1", child_session_id="child-1")
    assert phoenix_v7._last_tier_by_session["child-1"] == "l3_critical"

def test_subagent_start_parent_has_no_tier_is_noop():
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._on_subagent_start(parent_session_id="parent-2", child_session_id="child-2")
    assert "child-2" not in phoenix_v7._last_tier_by_session

def test_subagent_start_missing_ids_is_noop():
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._on_subagent_start(parent_session_id="", child_session_id="")
    assert phoenix_v7._last_tier_by_session == {}

def test_subagent_inherited_tier_triggers_high_tier_approval(monkeypatch):
    # 集成验证：继承来的 tier 真的会流进 _guard_tool()，触发高危档位审批门槛，
    # 不只是字典里有个值那么简单——这是本次改动要解决的真实空窗期。
    monkeypatch.setattr(phoenix_v7, "is_checkpoints_enabled", lambda: True)
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._last_tier_by_session["parent-3"] = "l3_critical"
    phoenix_v7._on_subagent_start(parent_session_id="parent-3", child_session_id="child-3")
    result = phoenix_v7._guard_tool("terminal", {"command": "ls"}, session_id="child-3")
    assert result is not None
    assert result["rule_key"] == "phoenix_v7_high_tier:terminal"

def test_subagent_own_route_overrides_inherited_tier(monkeypatch):
    # 继承值只补冷启动空窗期——子任务自己一旦被 _route() 分类过，用自己的判断
    # 结果覆盖继承值，不会永久锁死在父会话当时的档位上。
    phoenix_v7._last_tier_by_session.clear()
    phoenix_v7._last_tier_by_session["parent-4"] = "l3_critical"
    phoenix_v7._on_subagent_start(parent_session_id="parent-4", child_session_id="child-4")
    assert phoenix_v7._last_tier_by_session["child-4"] == "l3_critical"
    monkeypatch.setattr(phoenix_v7, "classify", lambda messages: "l0_quick")
    request = {"model": "default-model", "messages": [{"role": "user", "content": "在吗"}]}
    phoenix_v7._route(request, session_id="child-4")
    assert phoenix_v7._last_tier_by_session["child-4"] == "l0_quick"
