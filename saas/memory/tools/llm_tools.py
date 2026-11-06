"""LLM tool definitions for the memory module (OpenAI/Anthropic-style schema).

The AstrBot integration layer can register these with the agent runner; M2
ships the schema + dispatch so behaviour is testable without a model.
"""

from __future__ import annotations

from typing import Any

from .api import MemoryAPI

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "memory_remember",
        "description": "记住一条关于用户的重要信息（事实/偏好/事件/笔记）。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容，简洁陈述句"},
                "kind": {
                    "type": "string",
                    "enum": ["fact", "preference", "event", "note"],
                    "default": "fact",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选标签，如 人物/地点/项目",
                },
                "importance": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 3,
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "memory_recall",
        "description": "按关键词回忆与该用户相关的记忆。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                "kind": {
                    "type": "string",
                    "enum": ["fact", "preference", "event", "note"],
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_forget",
        "description": "删除一条不再需要的记忆。",
        "parameters": {
            "type": "object",
            "properties": {"memory_id": {"type": "integer"}},
            "required": ["memory_id"],
        },
    },
]


async def dispatch(
    api: MemoryAPI, bot_id: str, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    if name == "memory_remember":
        return api.remember(
            bot_id,
            str(arguments.get("content") or ""),
            kind=arguments.get("kind"),
            tags=arguments.get("tags") or [],
            importance=int(arguments.get("importance") or 3),
        )
    if name == "memory_recall":
        items = await api.recall(
            bot_id,
            str(arguments.get("query") or ""),
            top_k=int(arguments.get("top_k") or 5),
            kind=arguments.get("kind"),
        )
        return {"items": items, "prompt": api.format_for_prompt(items)}
    if name == "memory_forget":
        api.delete(bot_id, int(arguments.get("memory_id") or 0))
        return {"deleted": True}
    raise ValueError(f"未知记忆工具：{name}")
