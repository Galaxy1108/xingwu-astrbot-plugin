"""Always-inject memories, auto extraction, and memory service status."""

from __future__ import annotations

from saas.memory.auto_extract import extract_memories
from saas.memory.models import MemoryDraft


async def test_importance_six_always_recalled(container, invite):
    code = container.auth.request_otp("always@example.com", invite=invite)["dev_code"]
    user = container.auth.verify_otp("always@example.com", code, invite=invite)["user"]
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"], name="Always Bot", template_id=template["id"], platform="weixin_oc"
    )
    service = container.memory_service
    service.remember(
        bot["id"],
        MemoryDraft(content="用户希望每次回复都叫他老板", importance=6, kind="preference"),
    )
    service.remember(
        bot["id"],
        MemoryDraft(content="用户喜欢喝咖啡", importance=3, kind="preference"),
    )
    items = await service.recall(bot["id"], "今天天气怎么样")
    contents = [item.content for item in items]
    assert any("叫他老板" in text for text in contents)


async def test_auto_extract_patterns():
    drafts = extract_memories("请记住我住在杭州，以后都叫我小明")
    assert drafts
    assert all(1 <= item["importance"] <= 6 for item in drafts)
    assert any("杭州" in item["content"] or "小明" in item["content"] for item in drafts)
    assert extract_memories("今天天气怎么样？") == []


async def test_memory_status_reports_degraded(admin_api, container):
    from saas.memory.service import MEMORY_SETTINGS_KEY

    container.settings_store.set(
        MEMORY_SETTINGS_KEY,
        {
            "embedding": {
                "enabled": True,
                "base_url": "https://embedding.invalid/v1",
                "model": "m",
                "dimensions": 8,
            },
            "rerank": {"enabled": False},
            "behavior": {"auto_inject": True, "auto_extract": True},
        },
    )
    container.settings_store.set(
        "memory.health",
        {"embedding": {"ok": False, "error": "连接错误", "at": 1}},
    )
    response, body = await admin_api.get("/api/admin/settings/memory/status")
    assert response.status == 200
    status = body["data"]
    assert status["embedding"]["state"] == "degraded"
    assert status["embedding"]["last_error"] == "连接错误"
    assert status["rerank"]["state"] == "unconfigured"
    assert status["fts"]["available"] is True
