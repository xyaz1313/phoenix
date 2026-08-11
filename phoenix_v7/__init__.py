"""Phoenix V7 - Hermes Agent 插件.

最小核心：路由分档 / 成本与风险防线 / 自愈。
全部通过 Hermes 官方 middleware 接入，不修改任何 Hermes 核心文件。
"""
from __future__ import annotations

import logging
import yaml
from pathlib import Path

from hermes_constants import get_hermes_home

from .router.metis_core import classify
from .router.config import load_tier_overrides, write_enabled, resolve_candidate
from .guardrails.cost_monitor import CostMonitor
from .guardrails.circuit_breaker import CircuitBreaker
from .guardrails.model_health import ModelHealthTracker
from .guardrails.loop_signal import (
    _is_goal_active, _goal_created_at, _is_checklist_seeded, _mark_checklist_seeded,
)
from .guardrails.version_check import _read_hermes_version, check_hermes_compatibility
from .verify.hallucination import evaluate_response as _evaluate_hallucination
from .guardrails.tool_guard import (
    evaluate as _evaluate_tool_guard,
    evaluate_loop_checklist_gate as _evaluate_loop_checklist_gate,
)
from .guardrails.local_provider_guard import (
    is_turbofieldfare_target, check_local_provider_safety, TURBOFIELDFARE_PROVIDER,
    is_turbofieldfare_supported_platform,
)
from .guardrails.checkpoint_guard import (
    CHECKPOINT_REMINDER_TEXT, is_checkpoint_triggering_call, is_checkpoints_enabled,
)
from .guardrails.approval_trust import is_approval_trusted, record_approval_outcome
from .guardrails.webhook_export import send_alert
from .guardrails.focus_mode import is_focus_mode_enabled, set_focus_mode, focus_mode_status_line
from .guardrails.upgrade_watch import (
    check_version_transition, record_upgrade_anomaly,
    upgrade_summary_line, format_upgrade_log,
)
from .guardrails.context_watch import should_warn_context_size, context_size_warning_text
from .guardrails.fallback_watch import fallback_transition_text
from .memory.store import (
    search_memories as _search_memories,
    write_memory as _write_memory,
    forget_matching as _forget_memories_matching,
    clear_all as _clear_all_memories,
    stats as _memory_stats,
)
from .memory.threat_scan import contains_threat_pattern
from agent.memory_provider import is_trivial_prompt
from .privacy.keywords import detect_sensitive
from .privacy.warning import PRIVACY_WARNING_TEXT, append_privacy_warning  # noqa: F401 (PRIVACY_WARNING_TEXT re-exported for tests)
from agent.auxiliary_client import get_text_auxiliary_client
from .selfheal.antibody import AntibodyLibrary
from .selfheal.error_processor import ErrorProcessor

logger = logging.getLogger("phoenix_v7")

# session_id -> 最近一次路由判定的档位。Task 6 的 pre_tool_call 钩子读这份状态，判断
# "这一轮是不是高危档位，工具调用前要不要转人工审批"。进程内内存字典足够——重启插件
# （= 重启 hermes 进程）后清空是可接受的行为，不需要持久化。
_last_tier_by_session: dict[str, str] = {}

# session_id -> 这个session下一次API调用实际会用的模型（_route()每次被调用都刷新，
# 不管有没有真的换过）。最终整分支复审发现的真bug：_record_usage/_record_api_error
# 原本直接用 context.get("model")，那个值是 Hermes 的 agent.model——路由前的默认模型，
# _route() 换模型只改写了发出去的 request payload，从不回写 agent.model 本身。结果
# 健康追踪的成功/失败信号永远记在"没被真正调用过的模型"名下，候选链健康感知形同虚设
# （安全地退化成"永远选第一个候选"，不会锁死用户，但功能是死的）。这份字典就是记录
# "这个session这一轮真正会打给谁"，_record_usage/_record_api_error 优先读它。
_resolved_model_by_session: dict[str, str] = {}

# session_id -> 这次请求实际使用的 provider（_route() 每次调用都刷新，包括早退
# 路径）。transform_llm_output 钩子的 context 不带 provider 字段（已核实
# turn_finalizer.py 源码），只能靠这份缓存判断"这个session现在是不是在
# turbofieldfare上"。
_current_provider_by_session: dict[str, str] = {}

# session_id -> 这次请求是否走了 Hermes 原生 fallback_model 链（= _route() 算出来的
# on_primary_route 取反）。transform_llm_output 侧要判断"这一轮相对上一轮兜底状态
# 有没有变化"，同一份 on_primary_route 不能只算在 _route() 局部变量里，得存下来。
_on_fallback_by_session: dict[str, bool] = {}

# session_id -> 上一次检测到的兜底状态，用来跟这一轮的状态比较、判断有没有发生
# "刚切到兜底"或"刚切回主力"这类转变（fallback_watch.fallback_transition_text
# 只在状态真的变化时才返回提示文案，同一状态连续多轮不会重复刷屏）。
_previous_fallback_state_by_session: dict[str, bool] = {}

# session_id -> 这一轮 messages 是否命中隐私敏感词（_route() 每次调用都刷新，
# 包括早退路径，避免 transform_llm_output 侧读到陈旧值）。
_privacy_flagged_by_session: dict[str, bool] = {}

# session_id -> (钉住的模型, 钉住时的 provider)。会话粘滞（"只升不降"）：session 一旦
# 因高档位（如 l2_deep/l3_critical）被路由切到重模型，本会话后续请求保持该模型，即使
# classify() 把后面的消息判回低档位。原因：本地 26B 的"秒回"完全依赖 server 端 prefix
# 缓存，3B/26B 乒乓会让 26B 每次被切回来都是冷 prefix（2026-08-06 实测首轮 prefill
# 约 60s vs 缓存命中 3s）。钉住时记录 provider 是因为 _route() 只被允许在同 provider
# 内切换（2026-08-05 安全阀），换 provider 后钉子必须失效。
_pinned_route_by_session: dict[str, tuple[str, str]] = {}

# 已经提醒过隐私切换的 session 集合，避免同一会话反复提醒（见 Task 4）。
_privacy_warned_sessions: set[str] = set()

# 已经提醒过存档点的 session 集合，避免同一会话反复提醒。
_checkpoint_reminder_warned_sessions: set[str] = set()

_STATE_DIR = get_hermes_home() / "phoenix_v7_state"
# 2026-07-28修正：_cost_monitor 不再用来挡任何工具调用（原来 is_over_limit() 基于
# _USD_PER_1K_TOKENS 这个纯靠猜的费率，不对应任何具体模型真实计费，是2026-07-28那次
# 真机事故——熔断/成本上限跳闸后无差别锁死全部工具且无自救手段——的根源之一。用户复盘
# 后明确要求去掉这条基于猜测数字的拦截，只保留下面基于真实API报错次数的熔断器）。
# 仍然保留被动记账，写进 state/cost.json 供用户自己回头看开销趋势参考，不再有任何
# 阻断工具调用的效力。
_cost_monitor = CostMonitor(storage_path=_STATE_DIR / "cost.json")
_breaker = CircuitBreaker(failure_threshold=3, reset_after_seconds=300)
_model_health = ModelHealthTracker()
_USD_PER_1K_TOKENS = 0.002  # 粗估，仅供参考，不对应任何具体模型真实计费，不用于拦截判断
_antibody = AntibodyLibrary(storage_path=_STATE_DIR / "antibody.json")
_error_processor = ErrorProcessor(antibody=_antibody)

# session_id -> 是否有一次评判子Agent对这个session当前待执行的高危操作给出"通过"结论，
# 单次有效（_guard_tool 读到后立刻消费掉，不会重复放行）。V1已知限制：无法区分"这是
# 我方才提示模型委派的评判子Agent"还是"模型出于别的原因委派的某个无关子Agent"——只要
# child_summary 恰好以 APPROVED 开头就会被记成一次有效批准，触发条件很窄，V1接受这个
# 风险，不在这版加更严格的匹配（那需要不死鸟介入委派prompt编写，违反"不直接编排子Agent
# 调用"的设计原则）。
_pending_loop_approvals: dict[str, bool] = {}

_focus_mode_path: Path | None = None  # 测试用 monkeypatch 覆盖默认路径，生产环境保持 None 用默认路径

_memory_db_path: Path | None = None  # 测试用 monkeypatch 覆盖默认路径，生产环境保持 None 用默认路径

# session_id -> 这一轮用户消息文本，_route() 写入、_transform_output() 消费后写进
# 记忆库——两个钩子分别看得到请求和响应，配对写入需要靠这份缓存传递。
_pending_memory_write_by_session: dict[str, str] = {}

# session_id -> 本session连续弹出"需要确认"提示的次数（真的弹出才计数，
# 被信任/专注模式放行的不算）。达到3次时提醒一次可以开专注模式，之后不重复。
_consecutive_high_tier_prompts_by_session: dict[str, int] = {}
_focus_mode_suggested_sessions: set[str] = set()

_upgrade_watch_state_path: Path | None = None  # 测试用 monkeypatch 覆盖
_upgrade_watch_config_path: Path | None = None  # 测试用 monkeypatch 覆盖

# session_id -> 最新一轮 API 调用的 prompt_tokens（_record_usage 每次刷新）。
_prompt_tokens_by_session: dict[str, int] = {}
_context_size_warned_sessions: set[str] = set()

_HERMES_CONFIG_PATH = get_hermes_home() / "config.yaml"


def _load_primary_provider(path: Path | None = None) -> str:
    """读取 Hermes 根配置 model.provider，用来判断当前这次请求是不是走的主线路。

    Hermes 官方 fallback_model 链激活时，重试请求的 context["provider"] 会变成
    fallback 条目自己的 provider（不再是主 provider）——_route() 需要知道这件事，
    不然会在重试请求上again按档位把模型改回云端主力模型，抵消掉 Hermes 刚做的切换。
    读取失败（文件不存在/格式错误/字段缺失）返回空字符串，调用方把空字符串当作
    "跳过这项检查"处理，不能因为读配置失败就让每次请求都被误判成"不在主线路上"。
    """
    target = path or _HERMES_CONFIG_PATH
    if not target.exists():
        return ""
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    model_cfg = data.get("model")
    if not isinstance(model_cfg, dict):
        return ""
    provider = model_cfg.get("provider")
    return provider if isinstance(provider, str) else ""


_primary_provider = _load_primary_provider()


def _load_provider_base_url(provider_name: str, path: Path | None = None) -> str | None:
    """读取 config.yaml 里某个具名 provider 的 api 端点，用于 _providers_match()
    在 provider 名字比不上时兜底按端点比对。读取失败/字段缺失一律返回 None，
    调用方把 None 当"确认不了"处理。"""
    if not provider_name:
        return None
    target = path or _HERMES_CONFIG_PATH
    if not target.exists():
        return None
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    providers_cfg = data.get("providers")
    if not isinstance(providers_cfg, dict):
        return None
    provider_cfg = providers_cfg.get(provider_name)
    if not isinstance(provider_cfg, dict):
        return None
    api = provider_cfg.get("api")
    return api if isinstance(api, str) and api else None


def _providers_match(
    current_provider: str,
    current_base_url: str,
    target_provider_name: str,
    path: Path | None = None,
) -> bool:
    """判断当前请求实际打的 provider 是不是 target_provider_name（config.yaml
    里用户自己取的 provider 名，比如 "turbofieldfare"）。

    2026-08-11 真机测试实测发现：Hermes 对 `transport: chat_completions` 的
    自定义 provider，运行时传给插件 context["provider"] 的值统一被 Hermes 自己
    归一化成字面量 "custom"，不是 config.yaml 里那个用户自己取的 provider 名——
    直接比字符串永远对不上，_route() 的主线路判断和候选 provider 归属确认两处
    因此全程静默失效，本地档位路由从来没有真正生效过。不是猜的，是插了调试
    探针在真实对话里打印出来的。

    current_provider 是具名 provider（不是 "custom"）时，走原来的精确字符串
    比对——这条路径本身没问题，Hermes 内建 provider（nous/openai 等）的
    context["provider"] 就是 config.yaml 里那个名字。只有 current_provider
    命中 "custom" 这个歧义值时，才退化成按 base_url 精确匹配——base_url 是
    这次请求实际打的端点，不受 Hermes 内部 provider 类型归一化影响。"""
    if current_provider and current_provider != "custom":
        return current_provider == target_provider_name
    if not current_base_url:
        return False
    target_base_url = _load_provider_base_url(target_provider_name, path=path)
    if not target_base_url:
        return False
    return current_base_url.rstrip("/") == target_base_url.rstrip("/")


def _load_fallback_chain(path: Path | None = None) -> list[dict]:
    """读取 Hermes 根配置 fallback_model 链，跟 _load_primary_provider() 是同一种
    直接读 YAML 文件的模式。fallback_model 可以是单个 dict 或 dict 列表（chain），
    这里统一归一化成列表。读取失败一律返回空列表，调用方把空列表当"未配置"处理。"""
    target = path or _HERMES_CONFIG_PATH
    if not target.exists():
        return []
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    fb = data.get("fallback_model")
    if isinstance(fb, dict):
        fb = [fb]
    if not isinstance(fb, list):
        return []
    return [
        {"provider": entry["provider"], "model": entry["model"]}
        for entry in fb
        if isinstance(entry, dict) and "provider" in entry and "model" in entry
    ]

_PLUGIN_YAML_PATH = Path(__file__).resolve().parent / "plugin.yaml"


def _read_verified_hermes_version(path: Path | None = None) -> str | None:
    """读取 plugin.yaml 的 verified_hermes_version 字段——跟
    _load_primary_provider() 读 config.yaml 是同一种"直接读 YAML 文件"模式。
    读取失败（文件不存在/格式错误/字段缺失）返回 None，调用方降级成"无法读取"。"""
    target = path or _PLUGIN_YAML_PATH
    if not target.exists():
        return None
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("verified_hermes_version")
    return version if isinstance(version, str) else None


def _resolve_memory_db_path() -> Path:
    if _memory_db_path is not None:
        return _memory_db_path
    return _STATE_DIR / "memory.db"


def _latest_user_message(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            return content if isinstance(content, str) else ""
    return ""


# Hermes 官方 is_trivial_prompt() 的判定词表是纯英文（yes/no/thanks/ok...），不认识
# 中文打招呼/确认词——对不死鸟这种中文优先的产品，直接复用会漏过"谢谢""好的"这类
# 无语义轮次。补一个轻量中文判定，两边任一命中都算 trivial，跳过记忆写入。
_CHINESE_TRIVIAL_WORDS = frozenset({
    "谢谢", "谢了", "多谢", "好的", "好", "嗯", "嗯嗯", "收到", "了解", "明白",
    "知道了", "可以", "行", "对", "是的", "没问题", "OK", "ok", "okay",
})


def _is_trivial_chinese_prompt(text: str) -> bool:
    stripped = text.strip().strip("！!。.？?~～ ")
    return stripped in _CHINESE_TRIVIAL_WORDS


def _route(request: dict, **context) -> dict | None:
    current_provider = context.get("provider") or ""
    current_base_url = context.get("base_url") or ""
    session_id = context.get("session_id", "")
    messages = request.get("messages") or context.get("conversation_history") or []
    if session_id:
        _current_provider_by_session[session_id] = current_provider
        _privacy_flagged_by_session[session_id] = detect_sensitive(messages)
        user_text = _latest_user_message(messages)
        if user_text:
            _pending_memory_write_by_session[session_id] = user_text

    default_model = request.get("model", "")
    # 已经在 Hermes 的备用线路上时，不死鸟不插手模型选择——tier 判定/_last_tier_by_session
    # /_resolved_model_by_session 全部跳过是故意的：_guard_tool() 读不到 tier 时按
    # tier=None 处理，不会命中任何高危档位审批门槛，在降级状态下这是期望行为，不是遗漏。
    on_primary_route = not (
        _primary_provider
        and current_provider
        and not _providers_match(current_provider, current_base_url, _primary_provider)
    )
    if session_id:
        _on_fallback_by_session[session_id] = not on_primary_route

    tier = None
    new_model = default_model
    if on_primary_route:
        tier = classify(messages)
        if session_id:
            _last_tier_by_session[session_id] = tier

        enabled, overrides = load_tier_overrides()
        if enabled:
            tier_override = overrides.get(tier)
            new_model, candidate_provider = resolve_candidate(
                tier_override, default_model, _model_health
            )
            if new_model != default_model:
                # 2026-08-05修正：改写前必须能正向确认"候选模型属于当前请求的 provider"，
                # 而不是只在"两边都存在且不一致"时才拦截。候选没声明 provider（旧
                # string/list 格式）、或者当前请求 provider 本身缺失，都属于"归属无法
                # 确认"，跟"确认了但不一致"一样必须保留原模型——真实审计报告指出的
                # 根因就是这里以前默认放行"不确定"的情况，导致候选模型可能被发去
                # 错误的 provider 端点。
                provider_confirmed = (
                    candidate_provider is not None
                    and bool(current_provider)
                    and _providers_match(current_provider, current_base_url, candidate_provider)
                )
                if not provider_confirmed:
                    logger.warning(
                        "phoenix_v7 router: 候选模型 %s 的 provider 归属无法确认"
                        "（候选声明=%s，当前请求 provider=%s），跳过改写，保留原模型 %s",
                        new_model, candidate_provider, current_provider or "(缺失)", default_model,
                    )
                    new_model = default_model
            # 会话粘滞（只升不降）：本档位成功切到重模型 → 钉住；本档位落回默认模型
            # 且 session 有同 provider 的钉子 → 拔钉沿用，防 3B/26B 乒乓打死 26B 的
            # prefix 缓存。钉子在 routing 关闭、provider 变更时自然失效（不参与判断）。
            if session_id:
                if new_model != default_model:
                    _pinned_route_by_session[session_id] = (new_model, current_provider)
                else:
                    pin = _pinned_route_by_session.get(session_id)
                    if pin is not None and pin[1] == current_provider and pin[0] != default_model:
                        new_model = pin[0]
                        logger.info(
                            "phoenix_v7 router: session 已升级到 %s，保持粘滞"
                            "（本轮 tier=%s 落回默认，防 prefix 缓存乒乓失效）",
                            pin[0], tier,
                        )
        if session_id:
            _resolved_model_by_session[session_id] = new_model

    new_request = dict(request)
    changed = False

    if on_primary_route and new_model != default_model:
        new_request["model"] = new_model
        logger.info("phoenix_v7 router: tier=%s model %s -> %s", tier, default_model, new_model)
        changed = True

    # turbofieldfare 安全阀刻意放在上面"非主线路提前跳过"的判断之外——现实中触发这条
    # 路径的主要场景恰恰是 Hermes 原生 fallback_model 链把请求转去本地 turbofieldfare
    # （config.yaml 的 fallback_model 链已经指向 turbofieldfare/gemma-4-26b-a4b-it，
    # 见 docs/superpowers/specs/2026-08-02-local-provider-turbofieldfare-design.md），
    # 这时 current_provider 天然不等于 _primary_provider，如果把这段检查也挂在
    # on_primary_route 分支里，这道阀门在真实生产场景里就永远不会生效。
    if is_turbofieldfare_target(new_model, current_provider):
        safe, reason = check_local_provider_safety(messages)
        if not safe:
            logger.warning(
                "phoenix_v7 local-guard: 请求发给 turbofieldfare 但可能不安全(%s)——"
                "此层无法改道，仅记录", reason,
            )
        if new_request.get("stream"):
            new_request["stream"] = False
            logger.info("phoenix_v7 local-guard: 强制 turbofieldfare 请求 stream=False")
            changed = True

    if session_id and messages:
        latest_user_text = _latest_user_message(messages)
        if latest_user_text:
            recalled = _search_memories(_resolve_memory_db_path(), latest_user_text, limit=5)
            safe_snippets = []
            for item in recalled:
                is_threat, _label = contains_threat_pattern(item["content"])
                if not is_threat:
                    safe_snippets.append(item["content"])
            if safe_snippets:
                memory_block = "（不死鸟记忆库相关内容，供参考）\n" + "\n".join(
                    f"- {s}" for s in safe_snippets
                )
                new_request["messages"] = [
                    {"role": "system", "content": memory_block}
                ] + list(new_request.get("messages", messages))
                changed = True

    if not changed:
        return None  # 没变化就不用返回替换，减少 trace 噪音
    reason = f"tier={tier}" if tier is not None else "local-guard"
    return {"request": new_request, "source": "phoenix_v7", "reason": reason}


def _guard_tool(tool_name: str, args: dict, **context) -> dict | None:
    # 2026-07-28修正：不再用 _cost_monitor.is_over_limit(...) 的估算数字去挡工具调用
    # （那个费率是猜的，不是真实计费，是昨天事故的根源）。只看熔断器（基于真实API报错
    # 次数，更可信）。_cost_monitor 仍然在 _record_usage 里被动记账，供用户自己回头看
    # 开销趋势，只是不再拿它挡任何东西。
    session_id = context.get("session_id", "")
    if (
        session_id
        and is_checkpoint_triggering_call(tool_name, args)
        and not is_checkpoints_enabled()
        and session_id not in _checkpoint_reminder_warned_sessions
    ):
        _checkpoint_reminder_warned_sessions.add(session_id)
        logger.info("phoenix_v7 checkpoint: pre-tool warning for tool=%s", tool_name)
        return {
            "action": "approve",
            "message": CHECKPOINT_REMINDER_TEXT,
            "rule_key": "phoenix_v7_checkpoint_reminder",
        }
    tier = _last_tier_by_session.get(session_id)
    # Hermes 原生 cron 调度器给它触发的会话分配 "cron_<job_id>_..." 这样的
    # session_id（hermes-agent/cron/scheduler.py），不用不死鸟自己发明"这是调度
    # 触发的"新信号，直接检测这个既有前缀。
    is_scheduled = session_id.startswith("cron_")

    is_loop_active = _is_goal_active(session_id)
    goal_created_at = _goal_created_at(session_id) if is_loop_active else None
    checklist_seeded = (
        _is_checklist_seeded(session_id, goal_created_at)
        if is_loop_active and goal_created_at is not None
        else False
    )
    if is_loop_active:
        checklist_directive = _evaluate_loop_checklist_gate(
            tool_name, is_loop_active, checklist_seeded
        )
        if checklist_directive is not None:
            logger.info(
                "phoenix_v7 loop: tool=%s directive=%s", tool_name, checklist_directive["action"]
            )
            return checklist_directive

    command = args.get("command", "") if tool_name == "terminal" else ""
    is_hardline = False
    if command:
        try:
            from tools.approval import detect_hardline_command
            is_hardline, _ = detect_hardline_command(command)
        except Exception:
            is_hardline = False
    if is_hardline:
        send_alert(
            "hardline_command_detected", session_id,
            {"tool_name": tool_name, "command": command},
        )
    is_trusted = is_approval_trusted(tool_name) if tool_name else False

    directive = _evaluate_tool_guard(
        tier, _breaker.allow(), tool_name=tool_name, is_scheduled=is_scheduled,
        is_loop_active=is_loop_active, is_hardline=is_hardline, is_trusted=is_trusted,
        focus_mode=is_focus_mode_enabled(path=_focus_mode_path),
    )
    if (
        directive is not None
        and directive.get("rule_key", "").startswith("phoenix_v7_high_tier:")
        and session_id
    ):
        count = _consecutive_high_tier_prompts_by_session.get(session_id, 0) + 1
        _consecutive_high_tier_prompts_by_session[session_id] = count
        if count >= 3 and session_id not in _focus_mode_suggested_sessions:
            _focus_mode_suggested_sessions.add(session_id)
            directive["message"] += (
                "\n\n（这是本次会话第3次高危确认——如果想专心用固定模型干活，"
                "可以用 /phoenix-focus on 暂停这类提示）"
            )
    if (
        directive is not None
        and directive.get("rule_key") == "phoenix_v7_loop_high_tier_needs_evaluator"
        and _pending_loop_approvals.pop(session_id, False)
    ):
        logger.info("phoenix_v7 loop: evaluator approval consumed, allowing tool=%s", tool_name)
        directive = None

    # 只有这次调用最终判定为"放行"，才把 todo 记成"已经真正执行了一次种 checklist 的
    # 调用"。此前的 bug：seeded 标记在 _evaluate_tool_guard 判定之前就打上了——如果这次
    # todo 调用本身被高危档位挡下（评判子 Agent 还没批准），checklist 实际从未被真正
    # seed 过，却已经被标记成"seeded"，导致这个 loop 的 checklist gate 永久失效（评判
    # 拒绝时尤其明显）。
    if (
        directive is None
        and is_loop_active
        and tool_name == "todo"
        and not checklist_seeded
        and goal_created_at is not None
    ):
        _mark_checklist_seeded(session_id, goal_created_at)

    if directive is not None:
        logger.info("phoenix_v7 guardrails: tool=%s directive=%s", tool_name, directive["action"])
    return directive


def _on_subagent_stop(**context) -> None:
    parent_session_id = context.get("parent_session_id") or ""
    child_summary = (context.get("child_summary") or "").strip()
    if not parent_session_id or not child_summary:
        return
    if child_summary.upper().startswith("APPROVED"):
        _pending_loop_approvals[parent_session_id] = True
        logger.info(
            "phoenix_v7 loop: evaluator approved pending high-tier action for session=%s",
            parent_session_id,
        )


def _on_subagent_start(**context) -> None:
    """子任务生成瞬间，把父会话当前的风险档位复制给子会话——补上子任务自己
    第一次被 _route() 分类之前 tier=None 导致高危审批门槛失效的冷启动空窗期。
    父会话没有 tier（还没被分类过）时不写入，保持子任务原有的 None 行为不变。"""
    parent_session_id = context.get("parent_session_id") or ""
    child_session_id = context.get("child_session_id") or ""
    if not parent_session_id or not child_session_id:
        return
    parent_tier = _last_tier_by_session.get(parent_session_id)
    if parent_tier is not None:
        _last_tier_by_session[child_session_id] = parent_tier
        logger.info(
            "phoenix_v7 subagent: child=%s 继承父会话 tier=%s",
            child_session_id, parent_tier,
        )


def _on_session_start(**context) -> None:
    """检测Hermes版本是否变化——两次全新session之间发生过一次升级的话，
    备份config.yaml + 记一条transition，开启30分钟异常归档窗口。"""
    try:
        current = _read_hermes_version()
        check_version_transition(
            current, path=_upgrade_watch_state_path, config_path=_upgrade_watch_config_path,
        )
    except Exception:
        logger.debug("phoenix_v7 upgrade_watch: version check failed", exc_info=True)


def _check_privacy_warning(current_text: str, *, session_id: str) -> str | None:
    if not session_id:
        return None
    if not is_turbofieldfare_supported_platform():
        # turbofieldfare 是 Apple Silicon 专属（MLX 框架），Windows/Linux 用户
        # 不可能真的切过去——真实事故：Windows 用户装完提醒后照做，发现这个
        # provider 根本不存在，白白制造困惑。这类平台上不建议这条提醒。
        return None
    if not _privacy_flagged_by_session.get(session_id, False):
        return None
    if _current_provider_by_session.get(session_id, "") == TURBOFIELDFARE_PROVIDER:
        return None
    if session_id in _privacy_warned_sessions:
        return None
    _privacy_warned_sessions.add(session_id)
    return append_privacy_warning(current_text)


def _transform_output(**context) -> str | None:
    """transform_llm_output 分发函数：Hermes 只认第一个返回非空字符串的钩子，第二个
    独立注册的钩子返回值会被静默丢弃（已核实 turn_finalizer.py 源码）。幻觉核验和
    隐私事后提醒都要生效，所以必须合并进同一个函数里顺序调用、在同一个字符串上
    逐步叠加变更，而不是分别注册两个 transform_llm_output 钩子。"""
    response_text = context.get("response_text") or ""
    if not response_text:
        return None
    session_id = context.get("session_id", "")
    tier = _last_tier_by_session.get(session_id)

    current = response_text
    changed = False

    hallucination_result = _evaluate_hallucination(
        response_text, tier, lambda: get_text_auxiliary_client(task="hallucination_check")
    )
    if hallucination_result is not None:
        logger.info("phoenix_v7 verify: hallucination check flagged a response, tier=%s", tier)
        send_alert("hallucination_flagged", session_id, {"tier": tier})
        current = hallucination_result
        changed = True

    privacy_result = _check_privacy_warning(current, session_id=session_id)
    if privacy_result is not None:
        send_alert("privacy_warning_triggered", session_id, {})
        current = privacy_result
        changed = True

    prompt_tokens = _prompt_tokens_by_session.get(session_id, 0)
    if (
        session_id
        and should_warn_context_size(prompt_tokens)
        and session_id not in _context_size_warned_sessions
    ):
        _context_size_warned_sessions.add(session_id)
        current = f"{current}\n\n{context_size_warning_text(prompt_tokens)}"
        changed = True

    if session_id:
        current_on_fallback = _on_fallback_by_session.get(session_id, False)
        previous_on_fallback = _previous_fallback_state_by_session.get(session_id)
        notice = fallback_transition_text(
            previous_on_fallback=previous_on_fallback,
            current_on_fallback=current_on_fallback,
            model=context.get("model") or "",
        )
        _previous_fallback_state_by_session[session_id] = current_on_fallback
        if notice is not None:
            current = f"{current}\n\n{notice}"
            changed = True

    if session_id:
        pending_text = _pending_memory_write_by_session.pop(session_id, "")
        if (
            pending_text
            and not is_trivial_prompt(pending_text)
            and not _is_trivial_chinese_prompt(pending_text)
        ):
            _write_memory(_resolve_memory_db_path(), pending_text, session_id)

    return current if changed else None


def _resolved_model_for(context: dict) -> str | None:
    """优先用 _route() 记录的"这个session真正调用的模型"，兜底才用
    context.get("model")（= agent.model，_route() 从没被调用过这个session时的
    唯一信息来源，比如路由钩子因为某种原因没跑到）。"""
    session_id = context.get("session_id", "")
    if session_id and session_id in _resolved_model_by_session:
        return _resolved_model_by_session[session_id]
    return context.get("model")


def _record_usage(**context) -> None:
    usage = context.get("usage") or {}
    total_tokens = usage.get("total_tokens", 0) or 0
    usd = (total_tokens / 1000.0) * _USD_PER_1K_TOKENS
    _cost_monitor.record(usd)
    _breaker.record_success()
    model = _resolved_model_for(context)
    if model:
        _model_health.record_success(model)
    session_id = context.get("session_id", "")
    if session_id:
        _prompt_tokens_by_session[session_id] = usage.get("prompt_tokens", 0) or 0


def _record_api_error(**context) -> None:
    was_open = _breaker.state() == "open"
    _breaker.record_failure()
    if not was_open and _breaker.state() == "open":
        send_alert(
            "circuit_breaker_tripped",
            context.get("session_id", ""),
            {"error_type": (context.get("error") or {}).get("type")},
        )
    model = _resolved_model_for(context)
    error_type = (context.get("error") or {}).get("type")
    if model and error_type:
        _model_health.record_failure(model, error_type)
    record_upgrade_anomaly(
        "api_error", error_type or "unknown", path=_upgrade_watch_state_path,
    )


def _heal(tool_name: str, args: dict, next_call, **context):
    """tool_execution middleware：工具调用失败时查 antibody 表，命中就把处理建议
    附加进异常消息里带回给模型（下一轮它能看到"提示"自己决定要不要重试），未命中
    3次后升级提醒。

    没有按 Task 11 brief 原稿那样在这里对 next_call() 调用两次做"重试"：Hermes
    real middleware 契约（hermes_cli/middleware.py::_run_execution_chain，docs/
    middleware/README.md "Execution middleware should call next_call(...) exactly
    once"）明确 next_call 单次消费，第二次调用会直接抛 RuntimeError（"next_call()
    more than once"），不会真的重跑下游工具。改为查表 + 把 fix_hint 拼进异常消息
    向上抛，真正的重试落在模型看到提示后自己再发起一次工具调用（会重新进入这个
    middleware）。"""
    session_id = context.get("session_id", "")
    try:
        result = next_call(args)
    except Exception as exc:
        error_message = str(exc)
        record_upgrade_anomaly(
            "tool_error", f"{tool_name}: {error_message[:200]}",
            path=_upgrade_watch_state_path,
        )
        outcome = _error_processor.handle(tool_name=tool_name, error_message=error_message)
        if outcome.fix_hint:
            logger.info("phoenix_v7 selfheal: %s -> retrying with hint: %s", tool_name, outcome.fix_hint)
            matched_pattern = _antibody.match_pattern(error_message)
            if matched_pattern is not None:
                _antibody.record_outcome(matched_pattern, success=False)
                _error_processor.record_pending_fix(session_id, tool_name, matched_pattern)
            raise RuntimeError(f"{exc}\n[phoenix_v7 selfheal 建议] {outcome.fix_hint}") from exc
        if outcome.escalate:
            _antibody.record(error_message[:200], "未知错误，人工介入后请补充处理方式")
            logger.warning("phoenix_v7 selfheal: %s failed 3x, escalating to user: %s", tool_name, exc)
        raise
    else:
        pattern = _error_processor.pop_pending_fix(session_id, tool_name)
        if pattern is not None:
            _antibody.record_outcome(pattern, success=True)
            logger.info("phoenix_v7 selfheal: %s succeeded after hint, resetting failure streak for %r", tool_name, pattern)
        return result


# guardrails/tool_guard.py::evaluate() 返回 approve 时传的 rule_key 格式是
# "phoenix_v7_high_tier:{tool_name}"，这个 rule_key 最终会变成 Hermes 审批流程
# 里的 pattern_key，格式固定加了 "plugin_rule:" 前缀（tools/approval.py::
# request_tool_approval() 源码确认）。这个常量必须跟 rule_key 的格式保持同步。
_APPROVAL_PATTERN_KEY_PREFIX = "plugin_rule:phoenix_v7_high_tier:"


def _on_approval_response(**context) -> None:
    pattern_key = context.get("pattern_key") or ""
    if not pattern_key.startswith(_APPROVAL_PATTERN_KEY_PREFIX):
        return
    bucket_key = pattern_key[len(_APPROVAL_PATTERN_KEY_PREFIX):]
    choice = context.get("choice") or ""
    record_approval_outcome(bucket_key, choice)


def _setup_router_cli(subparser) -> None:
    subparser.add_argument("state", choices=["on", "off"], help="on=自动切换模型, off=只判断不切换")


def _handle_router_cli(args) -> None:
    enabled = args.state == "on"
    write_enabled(enabled)
    status = "已开启（会按档位自动切换模型）" if enabled else "已关闭（只判断档位，不切换模型）"
    print(f"phoenix_v7 自动路由: {status}")


def _setup_status_cli(subparser) -> None:
    pass


def _handle_status_cli(args) -> None:
    enabled, _overrides = load_tier_overrides()
    router_status = "自动挡" if enabled else "手动挡"
    breaker_state = _breaker.state()
    daily_cost = _cost_monitor.daily_total()
    antibody_stats = _antibody.stats()
    fallback_chain = _load_fallback_chain()
    if fallback_chain:
        chain_desc = " → ".join(f"{e['provider']}/{e['model']}" for e in fallback_chain)
        fallback_line = f"  欠费兜底链: {chain_desc}"
    else:
        fallback_line = "  欠费兜底链: 未配置"

    running_version = _read_hermes_version()
    verified_version = _read_verified_hermes_version()
    if verified_version is None:
        compat = "unknown"
    else:
        compat = check_hermes_compatibility(verified_version)
    if compat == "match":
        hermes_version_line = f"Hermes 版本: v{running_version}（已验证）"
    elif compat == "newer":
        hermes_version_line = (
            f"Hermes 版本: v{running_version}"
            f"（比不死鸟验证过的 v{verified_version} 新，建议核实一遍兼容性）"
        )
    elif compat == "older":
        hermes_version_line = (
            f"Hermes 版本: v{running_version}"
            f"（比不死鸟验证过的 v{verified_version} 旧，未测试过，可能有问题）"
        )
    else:
        hermes_version_line = "Hermes 版本: 无法读取（不影响不死鸟其它功能）"

    mem_counts = _memory_stats(_resolve_memory_db_path())

    print(
        "phoenix_v7 状态\n"
        f"  路由: {router_status}\n"
        f"  专注模式: {focus_mode_status_line()}\n"
        f"  版本变化: {upgrade_summary_line()}\n"
        f"  熔断器: {breaker_state}\n"
        "  长任务(Loop): 用 Hermes 原生 `/goal status` 查看（不死鸟在此基础上加了"
        "清单强制+高危操作复核，见 docs/Loop长任务使用指南.md）\n"
        f"  {hermes_version_line}\n"
        f"  今日花费(估算，非真实计费): ${daily_cost:.4f}\n"
        f"  抗体库: {antibody_stats['total_patterns']} 个已知模式"
        f"（{antibody_stats['disabled_patterns']} 个已停用）\n"
        f"{fallback_line}\n"
        f"  记忆库: {mem_counts['fact']} 条事实 / {mem_counts['belief']} 条信念 / "
        f"{mem_counts['observation']} 条待确认 / {mem_counts['archived']} 条已归档"
    )


def _handle_focus_slash(raw_args: str) -> str:
    """/phoenix-focus on|off|status —— 开关专注模式（暂停深度/真神档确认提示）。"""
    sub = raw_args.strip().lower().split()
    action = sub[0] if sub else "status"
    if action == "on":
        set_focus_mode(True, path=_focus_mode_path)
        return "phoenix_v7 专注模式：已开启（深度/真神档确认提示暂停，hardline永久高危命令不受影响）"
    if action == "off":
        set_focus_mode(False, path=_focus_mode_path)
        return "phoenix_v7 专注模式：已关闭（高危档位确认提示恢复正常）"
    if action == "status":
        return f"phoenix_v7 专注模式：{focus_mode_status_line(path=_focus_mode_path)}"
    return "用法：/phoenix-focus on | off | status"


def _handle_router_slash(raw_args: str, path: Path | None = None) -> str:
    """/phoenix-router on|off|status —— 开关自动路由换模型（phoenix-router终端
    命令的斜杠命令版本，桌面端/CLI对话中都能用）。"""
    sub = raw_args.strip().lower().split()
    action = sub[0] if sub else "status"
    if action == "on":
        write_enabled(True, path=path)
        return "phoenix_v7 自动路由：已开启（会按档位自动切换模型）"
    if action == "off":
        write_enabled(False, path=path)
        return "phoenix_v7 自动路由：已关闭（只判断档位，不切换模型）"
    if action == "status":
        enabled, _overrides = load_tier_overrides(path=path)
        return f"phoenix_v7 自动路由：{'自动挡' if enabled else '手动挡'}"
    return "用法：/phoenix-router on | off | status"


def _handle_upgrade_log_slash(raw_args: str) -> str:
    """/phoenix-upgrade-log —— 查看Hermes版本变化历史 + 变化后窗口期内记录的异常。"""
    return format_upgrade_log(path=_upgrade_watch_state_path)


def _handle_memory_slash(raw_args: str) -> str:
    """/phoenix-memory forget <关键词> | clear confirm —— 管理不死鸟自己的
    分层记忆库(独立于Hermes原生MEMORY.md)。"""
    parts = raw_args.strip().split(maxsplit=1)
    action = parts[0].lower() if parts else ""
    if action == "forget" and len(parts) > 1:
        removed = _forget_memories_matching(_resolve_memory_db_path(), parts[1])
        return f"phoenix_v7 记忆库：已删除 {removed} 条匹配「{parts[1]}」的记忆"
    if action == "clear":
        arg2 = parts[1].lower() if len(parts) > 1 else ""
        if arg2 != "confirm":
            return "确认要清空整个记忆库吗？请运行：/phoenix-memory clear confirm"
        removed = _clear_all_memories(_resolve_memory_db_path())
        return f"phoenix_v7 记忆库：已清空，共删除 {removed} 条记忆"
    return "用法：/phoenix-memory forget <关键词> | /phoenix-memory clear confirm"


def register(ctx) -> None:
    logger.info("phoenix_v7: plugin registered")
    ctx.register_middleware("llm_request", _route)
    ctx.register_hook("pre_tool_call", _guard_tool)
    ctx.register_hook("post_api_request", _record_usage)
    ctx.register_hook("api_request_error", _record_api_error)
    ctx.register_hook("subagent_start", _on_subagent_start)
    ctx.register_hook("subagent_stop", _on_subagent_stop)
    ctx.register_hook("post_approval_response", _on_approval_response)
    ctx.register_hook("transform_llm_output", _transform_output)
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_middleware("tool_execution", _heal)
    ctx.register_command(
        "phoenix-focus", handler=_handle_focus_slash,
        description="开关专注模式（暂停深度/真神档确认提示）",
    )
    ctx.register_command(
        "phoenix-router", handler=_handle_router_slash,
        description="开关自动路由换模型（终端命令 hermes phoenix-router 的斜杠命令版）",
    )
    ctx.register_command(
        "phoenix-upgrade-log", handler=_handle_upgrade_log_slash,
        description="查看Hermes版本变化历史+升级后窗口期内的异常记录",
    )
    ctx.register_command(
        "phoenix-memory", handler=_handle_memory_slash,
        description="管理不死鸟自己的分层记忆库(forget/clear)",
    )
    ctx.register_cli_command(
        "phoenix-router",
        help="开关不死鸟自动路由换模型",
        setup_fn=_setup_router_cli,
        handler_fn=_handle_router_cli,
        description="hermes phoenix-router on|off",
    )
    ctx.register_cli_command(
        "phoenix-status",
        help="查看不死鸟当前状态",
        setup_fn=_setup_status_cli,
        handler_fn=_handle_status_cli,
        description="hermes phoenix-status",
    )
