"""chat_history_search LLM tool: matching, limit, tenant isolation, fail-closed."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from saas.conversations_tools import (
    TOOL_DEFINITIONS,
    chat_history_search,
    dispatch,
)

ROOT = Path(__file__).resolve().parents[1]


def _load_plugin_main(tmp_path: Path):
    """Load ``main.py`` as the plugin package (it uses relative imports)."""
    pytest.importorskip("astrbot")
    from astrbot.core.star.star_tools import StarTools

    StarTools.get_data_dir = classmethod(lambda cls, name=None: tmp_path)
    package_name = "astrbot_plugin_saas"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(ROOT)]
        sys.modules[package_name] = package
    module_name = f"{package_name}.main"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


async def _user_and_bot(container, invite: str, email: str = "chat-tool@example.com"):
    code = container.auth.request_otp(email, invite=invite)["dev_code"]
    user = container.auth.verify_otp(email, code, invite=invite)["user"]
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"],
        name="聊天检索",
        template_id=template["id"],
        platform="weixin_oc",
    )
    return user, bot


async def _seeded_bot(container, invite: str, email: str = "chat-tool@example.com"):
    user, bot = await _user_and_bot(container, invite, email)
    coffee = await container.conversations.add_conversation(
        bot_id=bot["id"],
        title="咖啡入门",
        history=[
            {"role": "user", "content": "我想学手冲咖啡"},
            {"role": "assistant", "content": "可以先从 V60 和浅烘豆开始"},
        ],
    )
    work = await container.conversations.add_conversation(
        bot_id=bot["id"],
        title="出差计划",
        history=[{"role": "user", "content": "明天去杭州出差"}],
    )
    return user, bot, coffee, work


# ---------------------------------------------------------------------------
# search behaviour
# ---------------------------------------------------------------------------
async def test_search_chinese_substring(container, invite):
    user, bot, coffee, work = await _seeded_bot(container, invite)
    result = await chat_history_search(container.conversations, bot["id"], "咖啡")
    assert result["ok"] is True
    assert result["query"] == "咖啡"
    assert len(result["results"]) >= 1
    first = result["results"][0]
    assert first["conversation_id"] == coffee
    assert first["title"] == "咖啡入门"
    assert first["role"] == "user"
    assert "咖啡" in first["snippet"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", first["date"])
    assert all(item["conversation_id"] != work for item in result["results"])


async def test_search_multi_keyword_requires_all_tokens(container, invite):
    _, bot, _, _ = await _seeded_bot(container, invite)
    # "杭州 咖啡" spans two conversations → no single message matches both.
    result = await chat_history_search(
        container.conversations, bot["id"], "杭州 咖啡"
    )
    assert result["results"] == []
    single = await chat_history_search(container.conversations, bot["id"], "杭州")
    assert single["results"] and single["results"][0]["title"] == "出差计划"


async def test_search_limit_and_empty_query(container, invite):
    _, bot, _, _ = await _seeded_bot(container, invite)
    result = await chat_history_search(
        container.conversations, bot["id"], "我想学手冲咖啡", limit=1
    )
    assert len(result["results"]) == 1
    empty = await chat_history_search(container.conversations, bot["id"], "   ")
    assert empty["ok"] is False


async def test_search_isolated_between_bots(container, invite):
    _, bot_a, _, _ = await _seeded_bot(container, invite, "chat-a@example.com")
    other_invite = container.invites.create(created_by="system")["code"]
    _, bot_b = await _user_and_bot(container, other_invite, "chat-b@example.com")
    result = await chat_history_search(container.conversations, bot_b["id"], "咖啡")
    assert result["results"] == []
    own = await chat_history_search(container.conversations, bot_a["id"], "咖啡")
    assert own["results"]


async def test_search_missing_bot_returns_empty(container):
    result = await chat_history_search(container.conversations, "b_missing", "咖啡")
    assert result["ok"] is True
    assert result["results"] == []


async def test_dispatch_unknown_tool_raises(container):
    with pytest.raises(ValueError):
        await dispatch(container.conversations, "b", "nope", {})


def test_tool_schema():
    spec = TOOL_DEFINITIONS[0]
    assert spec["name"] == "chat_history_search"
    assert spec["parameters"]["required"] == ["query"]
    assert "query" in spec["parameters"]["properties"]


# ---------------------------------------------------------------------------
# main.py registration / fail-closed UMO handling
# ---------------------------------------------------------------------------
async def test_main_tool_fail_closed_on_unknown_umo(container, invite, tmp_path):
    module = _load_plugin_main(tmp_path)

    _, bot, _, _ = await _seeded_bot(container, invite, "chat-umo@example.com")
    plugin = object.__new__(module.SaaSBotPlugin)
    plugin.container = container

    rejected = SimpleNamespace(unified_msg_origin="weixin_oc:friend:session")
    payload = json.loads(
        await plugin._run_chat_tool(
            "chat_history_search", {"query": "咖啡"}, rejected
        )
    )
    assert payload["ok"] is False
    assert "租户" in payload["error"]

    accepted = SimpleNamespace(unified_msg_origin=f"{bot['id']}:friend:session")
    payload = json.loads(
        await plugin._run_chat_tool(
            "chat_history_search", {"query": "咖啡"}, accepted
        )
    )
    assert payload["ok"] is True
    assert payload["results"][0]["conversation_id"]
