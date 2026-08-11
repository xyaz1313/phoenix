"""上下文体量透明度——不猜Hermes内部真实压缩阈值（那套逻辑涉及模型注册表/
per-model覆盖/threshold_tokens_cap，插件层面拿不到准确数字，硬猜会误导用户），
改成通用粗粒度体量提醒：prompt_tokens 过一条启发式警戒线就提醒一次。

CONTEXT_WARN_TOKENS 是宽松保守初值，不是精确校准过的数字，跟
router/metis_core.py 的档位阈值同一个诚实态度，后续按真实反馈调。"""
from __future__ import annotations

CONTEXT_WARN_TOKENS = 100_000


def should_warn_context_size(prompt_tokens: int, threshold: int = CONTEXT_WARN_TOKENS) -> bool:
    return prompt_tokens >= threshold


def context_size_warning_text(prompt_tokens: int) -> str:
    return (
        f"（当前会话上下文已经比较大，约 {prompt_tokens:,} tokens——如果感觉AI"
        "开始变笨/跑偏/重复问过的问题，可能是上下文快被压缩了，建议开一个新"
        "会话继续，避免被压缩打断当前思路）"
    )
