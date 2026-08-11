"""pre_tool_call 钩子的纯判断逻辑 —— 对应V6.1 god_mode.py 的P0/P1/P2阈值设计,
触发点从"模型调用前"改成"工具调用前"（更贴近V6.1"$60悲剧"实际发生在工具循环失控这件事）.

2026-07-28修正一：真机验收撞上一次真实事故——熔断/成本上限跳闸后无差别锁死全部工具，
包括todo/memory这类不产生外部副作用、不触发新API调用的本地零风险操作，导致代理
（包括Hermes Agent自己）没有任何应用内自救手段，最终只能靠用户在Hermes外部手动清
配置解除。加一份低风险工具白名单，完全跳过熔断检查（但不跳过高危档位审批——白名单只免
跟系统健康有关的拦截，不代表这个工具本身被判定为高危档位时也能跳过人工确认）。

2026-07-28修正二：成本上限这条判断依据的是`_USD_PER_1K_TOKENS`这个纯靠猜的费率
（不对应任何具体模型真实计费），事故复盘后用户明确要求干脆去掉这条基于猜测数字的拦截，
只保留基于真实API报错次数的熔断器——熔断器更可信，不是猜的。cost_monitor.py这个模块
本身还留着做被动记账（`state/cost.json`会继续写，方便用户自己回头看开销趋势），只是
不再拿这个估算数字去挡任何工具调用。

2026-07-28修正三（V7.2 Loop）：新增两块跟"Loop长任务模式"相关的判断，都是独立于
熔断/成本之外的正交逻辑：
- evaluate_loop_checklist_gate()：Loop激活但清单还没建时，逼模型先用 todo 工具建清单，
  再做别的（白名单工具豁免，不产生新API调用、零风险，拦了没有意义）
- evaluate() 的 is_loop_active 参数：Loop 模式下高危档位不再指望人工审批（没人在场），
  换成"委派一个不同模型的评判子Agent复核"——这条不复用 is_scheduled（cron场景），
  两者是不同的处理策略，服务不同场景，同时为 True 时 is_scheduled 固定优先。"""
from __future__ import annotations

_HIGH_TIERS = ("l2_deep", "l3_critical")

# 零风险、不产生外部副作用、不触发新API调用的本地工具——熔断跳闸时依然放行，
# Loop 清单强制阶段也豁免（拦这些工具不会推进"建清单"这个目标，只会妨碍模型思考），
# 保证代理和用户任何时候都至少还能记笔记、查历史、看进度，不会被锁到完全没有自救手段。
SAFE_TOOL_WHITELIST = frozenset({"todo", "memory", "session_search"})

# delegate_task 是"委派评判子Agent复核"这个要求本身用来满足自己的工具——如果它也被
# 清单强制门槛或高危评判门槛拦住，模型会走进一个死循环：todo 命中高危门槛要求先
# delegate_task，delegate_task 命中清单门槛要求先 todo；就算清单已建，delegate_task
# 本身又是 tier in _HIGH_TIERS，会被高危门槛拿同一条"请先委派评判子Agent"的消息
# 拦下来，等于要求它先调用它自己。2026-08-01 真机测试撞见过这个死循环——连续 6 次
# 工具调用在 todo/delegate_task/terminal 之间互相拦截，从未解决。
# 不归进 SAFE_TOOL_WHITELIST：那个集合的语义是"零风险、不触发新API调用的本地工具"
# （见上面的注释），delegate_task 恰恰会触发一次新的模型调用，不是同一类，只是刚好
# 也需要在清单门槛和高危门槛这两处被单独豁免。
_DELEGATE_TASK_TOOL = "delegate_task"


def evaluate_loop_checklist_gate(
    tool_name: str | None,
    loop_active: bool,
    checklist_seeded: bool,
) -> dict | None:
    if not loop_active or checklist_seeded:
        return None
    if tool_name in SAFE_TOOL_WHITELIST or tool_name == _DELEGATE_TASK_TOOL:
        return None
    return {
        "action": "block",
        "message": (
            "phoenix_v7: Loop模式已激活，请先用 todo 工具列出具体步骤清单，"
            "再继续执行其他操作。"
        ),
        "rule_key": "phoenix_v7_loop_checklist_required",
    }


def evaluate(
    tier: str | None,
    breaker_allows: bool,
    tool_name: str | None = None,
    is_scheduled: bool = False,
    is_loop_active: bool = False,
    is_hardline: bool = False,
    is_trusted: bool = False,
    focus_mode: bool = False,
) -> dict | None:
    if tool_name not in SAFE_TOOL_WHITELIST and not breaker_allows:
        return {
            "action": "block",
            "message": (
                "phoenix_v7: 熔断器已跳闸，暂停工具调用。低风险工具（"
                + "、".join(sorted(SAFE_TOOL_WHITELIST))
                + "）不受影响。等待熔断自动恢复，或检查 "
                "不死鸟插件 state 目录下的 circuit_breaker.json 状态。"
            ),
        }
    if tier in _HIGH_TIERS:
        if is_scheduled:
            # 调度/Loop 触发的调用没有人在场按"批准"，走 approve 会永久挂起。
            # 但也不能因此直接放行——跳过执行，留下可审计的记录，而不是无人监督
            # 下直接跑。这条分支不受信任机制影响——is_trusted 只管"人工审批门槛
            # 要不要触发"，跟"无人在场时怎么处理"是两回事。
            return {
                "action": "block",
                "message": (
                    f"phoenix_v7: 当前任务判定为 {tier} 档位，但由调度/Loop自动触发，"
                    "没有人能实时批准，本次工具调用已跳过（未执行）。如需执行，请在"
                    "人工会话中手动确认。"
                ),
                "rule_key": "phoenix_v7_scheduled_high_tier_skip",
            }
        if is_loop_active:
            if tool_name == _DELEGATE_TASK_TOOL:
                # 正是用来满足下面这条"请先委派评判子Agent"要求的工具本身——不能
                # 被同一条规则拦住，那样它永远无法真正被委派出去。
                return None
            return {
                "action": "block",
                "message": (
                    f"phoenix_v7: 当前操作判定为 {tier} 档位，Loop模式下没有人工实时"
                    "批准。请先委派一个使用不同模型的评判子Agent复核这个操作是否应该"
                    "执行，评判子Agent确认无误后再重新发起这次工具调用。"
                ),
                "rule_key": "phoenix_v7_loop_high_tier_needs_evaluator",
            }
        # 信任机制 + 专注模式：同一工具类型连续批准够了，或者用户主动开了专注
        # 模式暂停提示，都不再触发确认——除非命中 Hermes 自己判定的永久高危命令
        # 类别，那条安全红线两者都不能覆盖。
        if (is_trusted or focus_mode) and not is_hardline:
            return None
        return {
            "action": "approve",
            "message": f"phoenix_v7: 当前任务判定为 {tier} 档位，需要确认后才能执行工具",
            "rule_key": f"phoenix_v7_high_tier:{tool_name}",
        }
    return None
