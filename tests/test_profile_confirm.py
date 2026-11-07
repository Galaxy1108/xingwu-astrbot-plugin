"""Profile display name + encrypted-content confirmation for admins."""

from __future__ import annotations

from conftest import ApiHelper


async def test_display_name_update_and_me(user_api: ApiHelper):
    response, body = await user_api.get("/api/me")
    assert body["data"]["user"]["display_name"]
    response, body = await user_api.patch(
        "/api/me/profile", json={"display_name": "小明"}
    )
    assert response.status == 200
    assert body["data"]["user"]["display_name"] == "小明"
    response, body = await user_api.get("/api/me")
    assert body["data"]["user"]["display_name"] == "小明"
    assert body["data"]["astrbot_dashboard_url"].startswith("http")


async def test_display_name_validation(user_api: ApiHelper):
    response, body = await user_api.patch("/api/me/profile", json={"display_name": ""})
    assert response.status == 400
    response, body = await user_api.patch(
        "/api/me/profile", json={"display_name": "x" * 40}
    )
    assert response.status == 400


async def test_admin_content_requires_confirmation_when_encrypted(
    admin_api: ApiHelper, container, invite
):
    code = container.auth.request_otp("confirmview@example.com", invite=invite)["dev_code"]
    user = container.auth.verify_otp(
        "confirmview@example.com", code, invite=invite
    )["user"]
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"], name="加密查看Bot", template_id=template["id"], platform="weixin_oc"
    )
    await container.conversations.add_conversation(
        bot_id=bot["id"],
        history=[{"role": "user", "content": "加密中的秘密"}],
    )

    response, body = await admin_api.get(f"/api/admin/bots/{bot['id']}/conversations")
    assert response.status == 403
    assert body["error"]["code"] == "confirmation_required"
    assert body["error"]["encrypted"] is True

    response, body = await admin_api.get(
        f"/api/admin/bots/{bot['id']}/conversations?confirm=1"
    )
    assert response.status == 200
    assert "加密中的秘密" in str(body["data"])
    log = container.db.query_one(
        "SELECT * FROM content_access_logs WHERE bot_id = ? AND resource = 'conversation'",
        (bot["id"],),
    )
    assert log is not None and log["reason"] == "confirmed_encrypted"

    # 用户关闭加密后，不再要求确认
    await container.encryption.start(
        user_id=user["id"], enabled=False, actor_id=user["id"], actor_role="user"
    )
    await container.encryption.wait_idle(user["id"])
    response, body = await admin_api.get(f"/api/admin/bots/{bot['id']}/memories")
    assert response.status == 200
