"""tier_overrides 配置文件读取，默认路径是不死鸟插件目录下的 config/tiers.json.

2026-07-28状态说明：当前这份配置是空字典 {}，是刻意留空，不是漏填。含义是——
classify()/tier_to_model() 这套"判断该用哪个档位"的逻辑照常运行、照常在日志里打印
tier=xxx，但因为没有任何档位配了对应模型，tier_to_model() 会一直落到 fallback（也就是
Hermes当前配置的默认模型），实际不会发生模型切换。这是用户在2026-07-28真机验收后明确
选择的过渡状态（"先不区分，只保留判断能力，风险更低"），不要在没有明确讨论过的情况下
自己往这里填模型名——填了就会真的开始按档位切模型，是一个有实际影响的产品决策，需要
用户确认要切哪些档位、切成什么模型。

2026-07-28（续，V7.1）：加了 enabled 开关，格式从纯 {tier: model} 平铺字典升级成
{"enabled": bool, "tiers": {tier: model}}。旧格式（含空字典 {}）继续兼容，读到旧格式
时 enabled 按 True 处理——但因为旧格式下 tiers 多半是空的，效果上跟"关闭"是一样的，
不会有任何用户因为这次升级突然被动"开启"了什么本来没配置过的东西。"""
from __future__ import annotations

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "tiers.json"


def load_tier_overrides(path: Path | None = None) -> tuple[bool, dict[str, str | list[str]]]:
    """返回 (enabled, tier_overrides)。

    新格式 {"enabled": bool, "tiers": {...}} 按字面读取。旧格式（纯 {tier: model}
    平铺字典，包括空字典）enabled 固定按 True 处理——旧格式没有 enabled 这个概念，
    这不是"猜"，是刻意选择跟旧行为完全等价的默认值。
    """
    target = path or _CONFIG_PATH
    if not target.exists():
        return True, {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return True, {}
    if not isinstance(data, dict):
        return True, {}
    if "enabled" in data and "tiers" in data:
        enabled = bool(data.get("enabled", True))
        tiers = data.get("tiers")
        if not isinstance(tiers, dict):
            tiers = {}
        return enabled, {k: v for k, v in tiers.items() if _is_valid_tier_value(v)}
    # 旧格式：纯 {tier: model} 平铺字典
    return True, {k: v for k, v in data.items() if _is_valid_tier_value(v)}


def _is_valid_tier_value(value) -> bool:
    """一个档位配的值合法当且仅当：单个模型字符串、一份纯字符串候选链列表，或者
    带 provider 归属声明的字典 {"model": str, "provider": str}。

    2026-07-29修正：这个过滤器最早只认字符串，V6.1机制移植加入候选链（列表）
    格式后没有同步更新，导致列表值被静默丢弃——Task 4 真机验证时才发现
    resolve_candidate() 永远收不到候选链，因为 load_tier_overrides() 在它之前
    就已经把列表值滤掉了。

    2026-08-03新增dict格式：真实测试者审计报告指出候选模型只存纯字符串，没有
    "这个模型属于哪个provider"这个字段，如果用户手动配置的候选模型名字实际属于
    别的provider，_route()会原样发出去导致对方端点报错——这是几周前tiers.json
    出厂配置泄漏事故的同一类根因换了个触发路径。dict格式让用户可以显式声明归属，
    _route()据此做校验（见__init__.py）。"""
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return bool(value) and all(isinstance(m, str) for m in value)
    if isinstance(value, dict):
        model = value.get("model")
        return isinstance(model, str) and bool(model)
    return False


def write_enabled(enabled: bool, path: Path | None = None) -> None:
    """改写 enabled 字段，保留（并在需要时升级）已有的 tiers 映射表。

    遇到旧格式（纯 {tier: model} 平铺字典，或文件不存在）时，把已有的 tier 映射
    原样搬进新格式的 "tiers" 字段，不丢用户已经填好的配置。
    """
    target = path or _CONFIG_PATH
    data: dict = {}
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}

    if "tiers" not in data or not isinstance(data.get("tiers"), dict):
        # 2026-08-05修正：以前这里只保留 isinstance(v, str) 的值，升级时会静默丢弃
        # 候选链（list）和 provider 归属声明（dict）格式的档位配置。改用跟
        # load_tier_overrides() 同一份合法性判断，三种格式都保留。
        old_tiers = {k: v for k, v in data.items() if _is_valid_tier_value(v)}
        data = {"tiers": old_tiers}

    data["enabled"] = enabled
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_candidate(
    tier_override: str | list[str] | dict | None,
    default_model: str,
    health,
) -> tuple[str, str | None]:
    """把 tiers.json 里某个档位的配置值解析成 (实际要用的模型字符串, 这个候选声明
    的 provider —— 没声明就是 None)。

    字符串/列表格式（旧格式）不带 provider 信息，返回的 provider 固定是 None。
    2026-08-05修正：_route() 现在把 provider=None 当成"归属无法确认"，会跳过改写、
    保留原模型（不再是"缺失就放行"）——旧格式配置升级后不会再实际切换模型，直到
    用户把对应档位改成 dict 格式 {"model": "...", "provider": "..."} 显式声明归属。
    这是真实审计报告指出的问题：以前默认放行"不确定归属"的候选，可能把模型请求
    发去它并不属于的 provider。

    候选链（列表）格式目前只支持纯字符串，不支持列表里混 dict——链式候选场景本来
    就是给"同一个 provider 下的模型故障转移"设计的，加 provider 归属校验的收益
    不大，这里刻意不做，YAGNI。

    字符串格式完全不触碰健康追踪——单模型用户没有候选链可言，这条路径必须
    零开销、零新增故障面。列表格式才会调用 health.ordered_candidates() 挑
    链里最健康的排第一个。"""
    if tier_override is None:
        return default_model, None
    if isinstance(tier_override, str):
        return tier_override, None
    if isinstance(tier_override, dict):
        model = tier_override.get("model")
        if not isinstance(model, str) or not model:
            return default_model, None
        provider = tier_override.get("provider")
        return model, (provider if isinstance(provider, str) and provider else None)
    if not tier_override:
        return default_model, None
    ordered = health.ordered_candidates(tier_override)
    return ordered[0], None
