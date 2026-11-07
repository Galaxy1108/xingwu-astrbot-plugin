"""Rule-based automatic memory extraction from a user/assistant turn."""

from __future__ import annotations

import re
from typing import Any

# Patterns that commonly encode durable user facts/preferences.
_PATTERNS: list[tuple[re.Pattern[str], str, int]] = [
    (re.compile(r"(?:请|帮我)?记住[：:，,\s]*(.+)"), "knowledge", 6),
    (re.compile(r"以后(?:都|每次)[，,\s]*(.+)"), "knowledge", 6),
    (re.compile(r"每次(?:对话|聊天|回复)[，,\s]*(.+)"), "knowledge", 6),
    (re.compile(r"我(?:最)?(?:喜欢|爱|偏好|更爱)(.+)"), "preference", 4),
    (re.compile(r"我(?:不喜欢|讨厌|受不了)(.+)"), "preference", 4),
    (re.compile(r"我(?:住在|来自|在)([^，。；\n]{2,40})"), "knowledge", 3),
    (re.compile(r"我(?:的)?(?:生日|名字|昵称|职业|工作)(?:是|叫)?([^，。；\n]{1,40})"), "knowledge", 4),
    (re.compile(r"(?:请)?(?:叫我|称呼我)([^，。；\n]{1,20})"), "preference", 4),
]

_STOPWORDS = ("吗", "呢", "啊", "吧", "呀")


def extract_memories(user_text: str, assistant_text: str = "") -> list[dict[str, Any]]:
    """Return candidate memory drafts from the latest user message.

    Conservative by design: only explicit/durable patterns, max 3 per turn,
    and never store pure questions or very long text.
    """
    text = re.sub(r"\s+", " ", str(user_text or "")).strip()
    if not text or len(text) > 500 or "?" in text or "？" in text:
        return []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern, kind, importance in _PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        content = match.group(1).strip(" ，,。.!！；;：:")
        if not content or len(content) < 2:
            continue
        if content in _STOPWORDS or content.endswith(("吗", "呢")):
            continue
        full = match.group(0).strip()
        if len(full) > 300:
            continue
        key = full.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "content": full,
                "kind": kind,
                "importance": max(1, min(6, importance)),
                "tags": ["自动提取"],
                "metadata": {"source": "auto_extract"},
            }
        )
        if len(results) >= 3:
            break
    return results
