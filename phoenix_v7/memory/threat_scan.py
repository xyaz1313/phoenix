"""检索出的记忆内容注入prompt前的威胁扫描——防止记忆库被投毒/注入攻击利用。
写法跟phoenix_v7/privacy/keywords.py同一个风格：纯正则/关键词匹配，不引入
检测框架/外部依赖。命中即丢弃该条记忆，不阻断当前请求(fail-safe)。"""
from __future__ import annotations

import re

_THREAT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
        "prompt_injection",
    ),
    (
        re.compile(r"忽略(之前|以上|上面)(所有)?(的)?指令"),
        "prompt_injection",
    ),
    (
        re.compile(r"^\s*system\s*:", re.IGNORECASE),
        "role_spoofing",
    ),
    (
        re.compile(r"<script[^>]*>", re.IGNORECASE),
        "xss",
    ),
    (
        re.compile(r"(\bunion\s+select\b|\bdrop\s+table\b|'\s*or\s*'1'\s*=\s*'1)", re.IGNORECASE),
        "sql_injection",
    ),
]


def contains_threat_pattern(text: str) -> tuple[bool, str | None]:
    for pattern, label in _THREAT_PATTERNS:
        if pattern.search(text):
            return True, label
    return False, None
