"""User-editable Bot settings (streaming/compression)."""

from __future__ import annotations

from conftest import ApiHelper


async def test_bot_settings_patch_and_validation(user_api: ApiHelper, container):
    user = container.auth.get_user_by_email("user@example.com")
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"],
        name="Settings Bot",
        template_id=template["id"],
        platform="weixin_oc",
    )
    response, body = await user_api.patch(
        f"/api/bots/{bot['id']}",
        json={
            "settings": {
                "streaming": True,
                "compression_max_turns": 12,
                "compression_overflow_strategy": "llm_compress",
            }
        },
    )
    assert response.status == 200
    saved = body["data"]["bot"]["settings"]
    assert saved["streaming"] is True
    assert saved["compression_max_turns"] == 12
    assert saved["compression_overflow_strategy"] == "llm_compress"
    response, body = await user_api.get(f"/api/bots/{bot['id']}")
    assert body["data"]["bot"]["settings"]["compression_max_turns"] == 12

    response, body = await user_api.patch(
        f"/api/bots/{bot['id']}",
        json={"settings": {"compression_max_turns": 0}},
    )
    assert response.status == 400
