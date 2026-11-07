"""LLM tool: search the current Bot's recent conversation history.

``chat_history_search(query, limit=5)`` returns keyword / Chinese-substring
matches from the histories of the Bot's recent conversations. The caller must
already have resolved the tenant ``bot_id`` from the UMO prefix (fail-closed in
``main.py``), so this module is pure lookup + formatting.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

MAX_LIMIT = 20
DEFAULT_LIMIT = 5
SNIPPET_LENGTH = 180
SNIPPET_CONTEXT = 40

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "chat_history_search",
        "description": "检索当前 Bot 最近对话记录中的相关片段（支持中文子串与关键词）。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要查找的关键词或短语，例如 '咖啡'、'杭州 工作'",
                },
                "limit": {
                    "type": "integer",
                    "default": DEFAULT_LIMIT,
                    "minimum": 1,
                    "maximum": MAX_LIMIT,
                    "description": "最多返回的片段数",
                },
            },
            "required": ["query"],
        },
    }
]


def _tokens(query: str) -> list[str]:
    return [token for token in re.split(r"\s+", (query or "").strip().lower()) if token]


def _snippet(text: str, tokens: list[str]) -> str:
    lowered = text.lower()
    index = -1
    for token in tokens:
        found = lowered.find(token)
        if found >= 0 and (index < 0 or found < index):
            index = found
    if index < 0:
        index = 0
    start = max(0, index - SNIPPET_CONTEXT)
    end = min(len(text), start + SNIPPET_LENGTH)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def _date(conversation: dict[str, Any]) -> str:
    timestamp = int(conversation.get("updated_at") or conversation.get("created_at") or 0)
    if timestamp <= 0:
        return ""
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def _title(conversation: dict[str, Any]) -> str:
    title = str(conversation.get("title") or "").strip()
    if title:
        return title
    for message in conversation.get("history") or []:
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip().replace("\n", " ")[:40]
    return ""


async def chat_history_search(
    conversations,
    bot_id: str,
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Search recent conversation histories for ``query``.

    Matching is case-insensitive and token-based: every whitespace-separated
    token must appear in a message (single-token queries therefore behave as a
    plain substring search, which covers Chinese).
    """
    text = str(query or "").strip()
    if not text:
        return {"ok": False, "error": "query 不能为空"}
    tokens = _tokens(text)
    if not tokens:
        return {"ok": False, "error": "query 不能为空"}
    try:
        capped = max(1, min(MAX_LIMIT, int(limit)))
    except (TypeError, ValueError):
        capped = DEFAULT_LIMIT

    items = await conversations.list_for_bot(bot_id, decrypt=True)
    results: list[dict[str, Any]] = []
    for conversation in items:
        title = _title(conversation)
        date = _date(conversation)
        for message in conversation.get("history") or []:
            content = message.get("content")
            if not isinstance(content, str):
                continue
            lowered = content.lower()
            if not all(token in lowered for token in tokens):
                continue
            results.append(
                {
                    "conversation_id": conversation.get("id", ""),
                    "title": title,
                    "date": date,
                    "role": str(message.get("role") or ""),
                    "snippet": _snippet(content, tokens),
                }
            )
            if len(results) >= capped:
                return {"ok": True, "query": text, "results": results}
    return {"ok": True, "query": text, "results": results}


async def dispatch(
    conversations,
    bot_id: str,
    name: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    arguments = arguments or {}
    if name != "chat_history_search":
        raise ValueError(f"未知对话工具：{name}")
    return await chat_history_search(
        conversations,
        bot_id,
        str(arguments.get("query") or ""),
        limit=int(arguments.get("limit") or DEFAULT_LIMIT),
    )


__all__ = ["TOOL_DEFINITIONS", "chat_history_search", "dispatch"]
