"""记忆置信度分层+衰减+强化——三层(Observation/Belief/Fact)不额外存字段，
读取时按分数区间动态推导。衰减是"读取时按经过时间现算"，不需要后台定时任务，
跟不死鸟其余模块的"按需触发"风格一致。"""
from __future__ import annotations

from datetime import datetime

CONFIDENCE_BELIEF_MIN = 0.5
CONFIDENCE_FACT_MIN = 0.85
CONFIDENCE_ARCHIVE_THRESHOLD = 0.15
CONFIDENCE_FLOOR = 0.05
INITIAL_CONFIDENCE = 0.5
REINFORCE_INCREMENT = 0.15
DECAY_PER_DAY = 0.02


def tier_for_confidence(confidence: float) -> str:
    if confidence >= CONFIDENCE_FACT_MIN:
        return "fact"
    if confidence >= CONFIDENCE_BELIEF_MIN:
        return "belief"
    return "observation"


def is_archived(confidence: float) -> bool:
    return confidence < CONFIDENCE_ARCHIVE_THRESHOLD


def decayed_confidence(initial_confidence: float, last_reinforced_at: datetime, now: datetime) -> float:
    days_elapsed = max((now - last_reinforced_at).total_seconds() / 86400.0, 0.0)
    decayed = initial_confidence - (DECAY_PER_DAY * days_elapsed)
    return max(decayed, CONFIDENCE_FLOOR)


def reinforce(current_confidence: float) -> float:
    return min(current_confidence + REINFORCE_INCREMENT, 1.0)
