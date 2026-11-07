"""M3 acceptance: encryption switch (全部解密 / 全部重新加密), backfill, access log."""

from __future__ import annotations

import sqlite3

import pytest

from conftest import ApiHelper
from saas.errors import AppError


async def _user_with_bot(container, invite, email="enc@example.com"):
    code = container.auth.request_otp(email, invite=invite)["dev_code"]
    user = container.auth.verify_otp(email, code, invite=invite)["user"]
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"], name="加密Bot", template_id=template["id"], platform="weixin_oc"
    )
    container.port.simulate_scan_complete(bot["id"])
    await container.qr.start(user_id=user["id"], bot_id=bot["id"])
    await container.qr.poll(user_id=user["id"], bot_id=bot["id"])
    await container.qr.finalize(user_id=user["id"], bot_id=bot["id"])
    await container.conversations.add_conversation(
        bot_id=bot["id"],
        title="测试对话",
        history=[
            {"role": "user", "content": "我喜欢在杭州西湖边散步"},
            {"role": "assistant", "content": "记住了，西湖边很适合散步。"},
        ],
    )
    return user, bot


async def _bot_for_user(container, user_id: str, name: str = "加密Bot"):
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user_id, name=name, template_id=template["id"], platform="weixin_oc"
    )
    container.port.simulate_scan_complete(bot["id"])
    await container.qr.start(user_id=user_id, bot_id=bot["id"])
    await container.qr.poll(user_id=user_id, bot_id=bot["id"])
    await container.qr.finalize(user_id=user_id, bot_id=bot["id"])
    await container.conversations.add_conversation(
        bot_id=bot["id"],
        title="测试对话",
        history=[
            {"role": "user", "content": "我喜欢在杭州西湖边散步"},
            {"role": "assistant", "content": "记住了，西湖边很适合散步。"},
        ],
    )
    return bot


async def _switch(container, user_id: str, enabled: bool) -> dict:
    await container.encryption.start(
        user_id=user_id,
        enabled=enabled,
        actor_id=user_id,
        actor_role="user",
    )
    return await container.encryption.wait_idle(user_id)


def _raw_conversation(container, bot_id: str) -> dict:
    return next(
        record
        for record in container.conversation_backend.records.values()
        if record.platform_id == bot_id
    )


async def test_decrypt_everything_then_encrypt_everything(container, invite):
    user, bot = await _user_with_bot(container, invite)
    bot_id = bot["id"]
    memory_path = container.settings.memory_dir / f"{bot_id}.db"
    assert container.memory_storage.is_encrypted(bot_id)
    assert _raw_conversation(container, bot_id).content[0]["content"].startswith("ENC1.")

    status = await _switch(container, user["id"], False)
    assert status["state"] == "plaintext"
    assert status["enabled"] is False
    # memory library is now plain SQLite and readable without SQLCipher
    assert container.memory_storage.is_encrypted(bot_id) is False
    conn = sqlite3.connect(memory_path)
    assert conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0] > 0
    conn.close()
    # credentials are plaintext JSON bytes
    row = container.db.query_one(
        "SELECT credential_cipher FROM bot_bindings WHERE bot_id = ?", (bot_id,)
    )
    assert bytes(row["credential_cipher"])[:1] == b"{"
    # conversation content is plaintext
    content = _raw_conversation(container, bot_id).content
    assert content[0]["content"].startswith("我") or "杭州" in str(content)

    status = await _switch(container, user["id"], True)
    assert status["state"] == "encrypted"
    assert status["enabled"] is True
    assert container.memory_storage.is_encrypted(bot_id)
    row = container.db.query_one(
        "SELECT credential_cipher FROM bot_bindings WHERE bot_id = ?", (bot_id,)
    )
    assert bytes(row["credential_cipher"])[:1] != b"{"
    assert _raw_conversation(container, bot_id).content[0]["content"].startswith("ENC1.")
    # decrypted view still works
    items = await container.conversations.list_for_bot(bot_id)
    assert "杭州" in items[0]["history"][0]["content"]


async def test_disable_requires_confirm_text_and_no_admin_disable(user_api, container):
    _, me = await user_api.get("/api/me")
    user = me["data"]["user"]
    bot = await _bot_for_user(container, user["id"], "确认Bot")
    response, _ = await user_api.put(
        "/api/me/encryption", json={"enabled": False, "confirm": "错的"}
    )
    assert response.status == 400
    response, _ = await user_api.put(
        "/api/me/encryption", json={"enabled": False, "confirm": "确认解密"}
    )
    assert response.status == 202
    await container.encryption.wait_idle(user["id"])
    response, body = await user_api.get("/api/me/encryption")
    assert body["data"]["state"] == "plaintext"

    with pytest.raises(AppError) as info:
        await container.encryption.start(
            user_id=user["id"], enabled=False, actor_id="admin", actor_role="admin"
        )
    assert info.value.status == 403


async def test_admin_content_view_writes_access_log(admin_api, container):
    user = container.auth.create_user("contentview@example.com")
    bot = await _bot_for_user(container, user["id"], "内容Bot")
    response, body = await admin_api.get(f"/api/admin/bots/{bot['id']}/conversations")
    assert response.status == 200
    assert body["data"]["items"][0]["history"][0]["content"].startswith("我喜欢")
    response, body = await admin_api.get(f"/api/admin/bots/{bot['id']}/memories")
    assert response.status == 200
    rows = container.db.query(
        "SELECT * FROM content_access_logs WHERE bot_id = ?", (bot["id"],)
    )
    assert {row["resource"] for row in rows} == {"conversation", "memory"}
    # user-side access log is queryable from the same table
    log = container.audit.access_log(user_id=user["id"])
    assert log["total"] >= 2
    assert any(item["resource"] == "conversation" for item in log["items"])


async def test_encryption_switch_conflict_while_running(container, invite):
    user, bot = await _user_with_bot(container, invite, "race@example.com")
    await container.encryption.start(
        user_id=user["id"], enabled=False, actor_id=user["id"], actor_role="user"
    )
    with pytest.raises(AppError) as info:
        await container.encryption.start(
            user_id=user["id"], enabled=False, actor_id=user["id"], actor_role="user"
        )
    assert info.value.status == 409
    await container.encryption.wait_idle(user["id"])
