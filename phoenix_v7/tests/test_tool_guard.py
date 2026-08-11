import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guardrails.tool_guard import evaluate


def test_normal_tier_allows_without_directive():
    assert evaluate(tier="l1_daily", breaker_allows=True) is None


def test_breaker_open_blocks():
    result = evaluate(tier="l1_daily", breaker_allows=False)
    assert result["action"] == "block"


def test_high_tier_requires_approval():
    result = evaluate(tier="l2_deep", breaker_allows=True)
    assert result["action"] == "approve"
    assert result["rule_key"] == "phoenix_v7_high_tier:None"


def test_breaker_check_takes_priority_over_tier():
    # 熔断器已经跳闸时，直接 block，不需要再走 approve 流程多问一次
    result = evaluate(tier="l3_critical", breaker_allows=False)
    assert result["action"] == "block"


def test_whitelisted_tool_bypasses_breaker_block():
    # 2026-07-28真机事故: 熔断跳闸后无差别锁死全部工具(包括todo/memory这类零风险、
    # 不产生新API调用的本地操作)，且没有任何应用内自救手段，最终只能靠用户在Hermes
    # 外部手动清配置解除。白名单工具必须完全跳过熔断检查。
    result = evaluate(tier="l1_daily", breaker_allows=False, tool_name="todo")
    assert result is None


def test_whitelisted_tool_still_requires_approval_at_high_tier():
    # 白名单只免熔断拦截,不免高危档位人工确认——白名单工具本身零风险,但如果被
    # 判定为l2_deep/l3_critical档位(理论上不太会,但不能假设分类器不会分错),还是要走
    # 正常审批流程,不能变成"报了白名单名字就完全免检"。
    result = evaluate(tier="l2_deep", breaker_allows=True, tool_name="todo")
    assert result["action"] == "approve"


def test_non_whitelisted_tool_still_blocked():
    result = evaluate(tier="l1_daily", breaker_allows=False, tool_name="terminal")
    assert result["action"] == "block"


def test_scheduled_high_tier_call_is_skipped_not_executed():
    # Loop/cron 触发的调用没有人在场按"批准"，高危档位如果还走 approve 流程会
    # 永久卡住等不到批准。但也不能因此直接放行——用户要求的是"事后可见的跳过"，
    # 而不是"无人监督下直接执行"。所以是 block（工具确实没执行），不是 None（放行）
    # 也不是 approve（会挂起等一个不会出现的人）。
    result = evaluate(tier="l3_critical", breaker_allows=True, is_scheduled=True)
    assert result["action"] == "block"
    assert result["rule_key"] == "phoenix_v7_scheduled_high_tier_skip"


def test_scheduled_call_still_blocked_by_breaker():
    # 熔断器只跟"系统是不是在连续出错"有关，跟谁发起调用无关——调度触发的调用
    # 一样要被熔断挡住，is_scheduled 只免人工审批，不免熔断保护。
    result = evaluate(tier="l1_daily", breaker_allows=False, is_scheduled=True)
    assert result["action"] == "block"


def test_non_scheduled_high_tier_call_still_requires_approval():
    # 默认 is_scheduled=False，人类发起的高危档位调用行为不变，这是最基本的
    # 回归保证——不能因为加了调度豁免就误伤了正常的人工审批流程。
    result = evaluate(tier="l2_deep", breaker_allows=True, is_scheduled=False)
    assert result["action"] == "approve"


def test_cost_limit_no_longer_gates_tool_calls():
    # 2026-07-28修正二: 成本上限判断依据的是纯靠猜的费率,不是真实计费,事故复盘后用户
    # 明确要求去掉这条基于猜测数字的拦截, 只保留基于真实API报错次数的熔断器。evaluate()
    # 不再接受 over_cost_limit 参数——如果调用方仍然传了这个关键字参数应该直接报错，
    # 而不是被默默接受又不起作用(那样才是真正的"看起来在管，实际上没生效"的假保护)。
    import pytest

    with pytest.raises(TypeError):
        evaluate(tier="l1_daily", breaker_allows=True, over_cost_limit=True)


def test_checklist_gate_inactive_loop_returns_none():
    from guardrails.tool_guard import evaluate_loop_checklist_gate

    assert evaluate_loop_checklist_gate("terminal", loop_active=False, checklist_seeded=False) is None


def test_checklist_gate_seeded_returns_none():
    from guardrails.tool_guard import evaluate_loop_checklist_gate

    assert evaluate_loop_checklist_gate("terminal", loop_active=True, checklist_seeded=True) is None


def test_checklist_gate_blocks_non_whitelisted_tool_before_seeded():
    from guardrails.tool_guard import evaluate_loop_checklist_gate

    result = evaluate_loop_checklist_gate("terminal", loop_active=True, checklist_seeded=False)
    assert result["action"] == "block"
    assert result["rule_key"] == "phoenix_v7_loop_checklist_required"


def test_checklist_gate_allows_todo_before_seeded():
    from guardrails.tool_guard import evaluate_loop_checklist_gate

    assert evaluate_loop_checklist_gate("todo", loop_active=True, checklist_seeded=False) is None


def test_checklist_gate_allows_whitelisted_memory_before_seeded():
    # 白名单里 memory/session_search 是已确认的零风险只读工具，清单没建好之前
    # 拦这两个没有意义，只会妨碍模型正常思考——豁免整个白名单，不是只豁免 todo
    from guardrails.tool_guard import evaluate_loop_checklist_gate

    assert evaluate_loop_checklist_gate("memory", loop_active=True, checklist_seeded=False) is None


def test_loop_active_high_tier_blocks_with_evaluator_instruction():
    result = evaluate(tier="l3_critical", breaker_allows=True, is_loop_active=True)
    assert result["action"] == "block"
    assert result["rule_key"] == "phoenix_v7_loop_high_tier_needs_evaluator"


def test_loop_and_scheduled_both_true_scheduled_takes_priority():
    # 固定顺序：两者都为 True 时 is_scheduled 分支先命中。V1 里这个组合实际不会
    # 发生（Loop 只能手动启动），但代码行为必须是确定的，不是未定义的。
    result = evaluate(
        tier="l3_critical", breaker_allows=True, is_scheduled=True, is_loop_active=True
    )
    assert result["rule_key"] == "phoenix_v7_scheduled_high_tier_skip"


def test_loop_inactive_high_tier_unaffected():
    # 回归保证：is_loop_active 默认 False 时行为不变
    result = evaluate(tier="l2_deep", breaker_allows=True)
    assert result["rule_key"] == "phoenix_v7_high_tier:None"


def test_checklist_gate_allows_delegate_task_before_seeded():
    # 2026-08-01 真机测试撞见的死循环：delegate_task 不在 SAFE_TOOL_WHITELIST 里，
    # 清单未建时会被这道门拦住——但 delegate_task 正是用来委派评判子Agent、满足
    # 高危档位门槛要求的工具，不能被"先建清单"这条规则先一步拦死。
    from guardrails.tool_guard import evaluate_loop_checklist_gate

    assert evaluate_loop_checklist_gate("delegate_task", loop_active=True, checklist_seeded=False) is None


def test_loop_active_high_tier_allows_delegate_task_itself():
    # 同一次真机死循环的另一半：高危档位门槛原本对 delegate_task 也返回"请先委派
    # 评判子Agent复核"，等于让这个工具自己拦自己，永远没有出路。真机日志显示连续
    # 6 次工具调用在 todo/delegate_task/terminal 之间互相拦截，从未解决。
    result = evaluate(
        tier="l3_critical", breaker_allows=True, tool_name="delegate_task", is_loop_active=True
    )
    assert result is None


def test_loop_active_high_tier_still_blocks_non_delegate_tools():
    # 回归保证：豁免只针对 delegate_task 本身，其他高危工具调用照常被拦，不能因为
    # 修死锁就把整个高危审批门槛开了后门。
    result = evaluate(
        tier="l3_critical", breaker_allows=True, tool_name="terminal", is_loop_active=True
    )
    assert result["rule_key"] == "phoenix_v7_loop_high_tier_needs_evaluator"


def test_high_tier_requires_approval_rule_key_includes_tool_name():
    result = evaluate(tier="l2_deep", breaker_allows=True, tool_name="write_file")
    assert result["rule_key"] == "phoenix_v7_high_tier:write_file"


def test_different_tools_get_different_rule_keys():
    result_a = evaluate(tier="l2_deep", breaker_allows=True, tool_name="write_file")
    result_b = evaluate(tier="l2_deep", breaker_allows=True, tool_name="terminal")
    assert result_a["rule_key"] != result_b["rule_key"]


def test_trusted_high_tier_call_skips_approval():
    result = evaluate(
        tier="l2_deep", breaker_allows=True, tool_name="write_file", is_trusted=True,
    )
    assert result is None


def test_untrusted_high_tier_call_still_requires_approval():
    result = evaluate(
        tier="l2_deep", breaker_allows=True, tool_name="write_file", is_trusted=False,
    )
    assert result["action"] == "approve"


def test_hardline_command_requires_approval_even_when_trusted():
    # 安全红线：不管历史批准多少次，命中 Hermes 自己判定的永久高危命令类别，
    # 信任机制不能覆盖这道保护。
    result = evaluate(
        tier="l3_critical", breaker_allows=True, tool_name="terminal",
        is_trusted=True, is_hardline=True,
    )
    assert result["action"] == "approve"


def test_trusted_but_not_hardline_still_skips():
    # 上一条测试的对照组：确认不是"只要is_hardline参数存在就总是拦"，
    # 而是精确只在 is_hardline=True 时才拦。
    result = evaluate(
        tier="l3_critical", breaker_allows=True, tool_name="terminal",
        is_trusted=True, is_hardline=False,
    )
    assert result is None


def test_scheduled_high_tier_ignores_trust():
    # 调度/Loop触发的调用走的是"block，事后可见的跳过"这条分支，跟人工审批+
    # 信任机制完全无关——is_trusted=True 不该让这条分支的行为发生变化。
    result = evaluate(
        tier="l3_critical", breaker_allows=True, is_scheduled=True, is_trusted=True,
    )
    assert result["action"] == "block"
    assert result["rule_key"] == "phoenix_v7_scheduled_high_tier_skip"


def test_focus_mode_high_tier_call_skips_approval():
    result = evaluate(
        tier="l2_deep", breaker_allows=True, tool_name="write_file", focus_mode=True,
    )
    assert result is None


def test_focus_mode_off_high_tier_call_still_requires_approval():
    result = evaluate(
        tier="l2_deep", breaker_allows=True, tool_name="write_file", focus_mode=False,
    )
    assert result["action"] == "approve"


def test_focus_mode_does_not_bypass_hardline_command():
    # 专注模式跟信任机制一样，拦不住 hardline 永久高危命令类别。
    result = evaluate(
        tier="l3_critical", breaker_allows=True, tool_name="terminal",
        focus_mode=True, is_hardline=True,
    )
    assert result["action"] == "approve"


def test_focus_mode_and_trust_both_false_still_requires_approval():
    result = evaluate(
        tier="l2_deep", breaker_allows=True, tool_name="write_file",
        focus_mode=False, is_trusted=False,
    )
    assert result["action"] == "approve"
