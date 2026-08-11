"""兜底状态透明提醒——Hermes 原生 fallback_model 链本身已经会自动切到兜底、
自动探测主力恢复后切回（agent/agent_runtime_helpers.py::restore_primary_runtime()，
每轮新消息都会重试），不死鸟不用重新实现这套切换逻辑，只是把切换这件事从"静默
发生"变成"用户看得见"：状态真的变化时提醒一句，没变化不重复刷屏。"""
from __future__ import annotations


def fallback_transition_text(
    *, previous_on_fallback: bool | None, current_on_fallback: bool, model: str = "",
) -> str | None:
    """previous_on_fallback 是 None 代表这个 session 还从没被检测过（可能是新会话，
    也可能是从一开始就已经在兜底上）——两种情况都不该提示"刚刚切换"，因为我们并
    不知道这次切换是不是这一轮才发生的，只有真正观察到状态从一个值变成另一个值
    才算数。"""
    if previous_on_fallback is None:
        return None
    if previous_on_fallback == current_on_fallback:
        return None
    if current_on_fallback:
        model_desc = f"（{model}）" if model else ""
        return (
            f"⚠️ 主力模型暂时不可用，本轮已自动切到兜底模型{model_desc}处理。"
            "Hermes 会在后续每轮自动重试主力，恢复后自动切回，不需要手动操作。"
        )
    return "✅ 主力模型已恢复，已自动切回，不再使用兜底模型。"
