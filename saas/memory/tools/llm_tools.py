"""LLM tool definitions for the memory module (OpenAI/Anthropic-style schema).

The AstrBot integration layer registers these with the agent runner; M2 ships
the schema + dispatch so behaviour is testable without a model.
"""

from __future__ import annotations

from typing import Any

from ..api import MemoryAPI

# ``fact`` is kept for backwards compatibility (legacy libraries/prompts);
# new prompts should use ``knowledge``.
_KIND_ENUM = [
    "knowledge",
    "preference",
    "relationship",
    "event",
    "emotion",
    "note",
    "fact",
]

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "memory_remember",
        "description": "记住一条关于用户的重要信息（知识/偏好/关系/事件/情感/笔记）。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容，简洁陈述句"},
                "kind": {
                    "type": "string",
                    "enum": _KIND_ENUM,
                    "default": "knowledge",
                    "description": "记忆分类；fact 是 knowledge 的兼容写法",
                },
                "memory_type": {
                    "type": "string",
                    "enum": _KIND_ENUM,
                    "description": "记忆类型（与 kind 等价，优先使用 memory_type）",
                },
                "strength": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "default": 50,
                    "description": "记忆强度 0-100，越高越不容易被遗忘",
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
                "kind": {"type": "string", "enum": _KIND_ENUM},
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
    {
        "name": "memory_note_create",
        "description": (
            "把成体系的知识整理成一篇 Markdown 笔记永久存档，自动纳入笔记库，之后可检索。"
            "用多级标题（#/##）分节，方便日后按段展开。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "笔记标题，简短概括主题。例：'Python异步编程'",
                },
                "content": {
                    "type": "string",
                    "description": "笔记正文，Markdown 格式，建议用多级标题组织结构。",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选标签",
                },
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "memory_note_read",
        "description": "按短 ID 分页读取笔记正文（offset/limit 为字符偏移）。",
        "parameters": {
            "type": "object",
            "properties": {
                "short_id": {
                    "type": "string",
                    "description": "笔记短 ID（6–8 位可读 ID，例如 'k3m9x2'）",
                },
                "offset": {
                    "type": "integer",
                    "description": "起始字符偏移（从 0 开始）",
                    "minimum": 0,
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "最多读取的字符数（默认 4000，上限 20000）",
                    "minimum": 1,
                    "maximum": 20000,
                },
            },
            "required": ["short_id"],
        },
    },
]


async def dispatch(
    api: MemoryAPI, bot_id: str, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    arguments = arguments or {}
    if name == "memory_remember":
        return api.remember(
            bot_id,
            str(arguments.get("content") or ""),
            kind=arguments.get("kind"),
            memory_type=arguments.get("memory_type"),
            strength=(
                int(arguments["strength"]) if arguments.get("strength") is not None else None
            ),
            tags=arguments.get("tags") or [],
            importance=int(arguments.get("importance") or 3),
        )
    if name == "memory_recall":
        items = await api.recall(
            bot_id,
            str(arguments.get("query") or ""),
            top_k=int(arguments["top_k"]) if arguments.get("top_k") else None,
            kind=arguments.get("kind"),
        )
        return {"items": items, "prompt": api.format_for_prompt(items)}
    if name == "memory_forget":
        api.delete(bot_id, int(arguments.get("memory_id") or 0))
        return {"deleted": True}
    if name == "memory_note_create":
        return api.note_create(
            bot_id,
            str(arguments.get("title") or ""),
            str(arguments.get("content") or ""),
            tags=arguments.get("tags") or [],
        )
    if name == "memory_note_read":
        return api.note_read(
            bot_id,
            str(arguments.get("short_id") or ""),
            offset=int(arguments.get("offset") or 0),
            limit=int(arguments.get("limit") or 4000),
        )
    raise ValueError(f"未知记忆工具：{name}")
