"""Conversation history viewing + public share links."""

from __future__ import annotations

from conftest import ApiHelper


async def _bot(api: ApiHelper, name: str = "对话 Bot") -> dict:
    _, body = await api.get("/api/templates")
    template_id = body["data"]["items"][0]["id"]
    _, body = await api.post(
        "/api/bots",
        json={"name": name, "template_id": template_id, "platform": "weixin_oc"},
    )
    return body["data"]["bot"]


async def _add(api: ApiHelper, bot: dict, title: str, history: list[dict]) -> str:
    response, body = await api.post(
        f"/api/dev/bots/{bot['id']}/conversations",
        json={"title": title, "history": history},
    )
    assert response.status == 200, body
    return body["data"]["conversation_id"]


HISTORY = [
    {"role": "user", "content": "我想学手冲咖啡"},
    {"role": "assistant", "content": "可以先从 V60 和浅烘豆开始"},
]


# ---------------------------------------------------------------------------
# owner history
# ---------------------------------------------------------------------------
async def test_owner_lists_and_reads_conversations(user_api: ApiHelper, container):
    bot = await _bot(user_api)
    first = await _add(user_api, bot, "咖啡入门", HISTORY)
    await _add(user_api, bot, "周末计划", [{"role": "user", "content": "去西湖"}])

    response, body = await user_api.get(
        f"/api/bots/{bot['id']}/conversations?page=1&page_size=1"
    )
    assert response.status == 200
    data = body["data"]
    assert data["total"] == 2
    assert data["page"] == 1 and data["page_size"] == 1
    assert len(data["items"]) == 1
    assert set(data["items"][0]) >= {
        "id",
        "title",
        "created_at",
        "updated_at",
        "message_count",
    }

    response, body = await user_api.get(
        f"/api/bots/{bot['id']}/conversations/{first}"
    )
    assert response.status == 200
    conversation = body["data"]["conversation"]
    assert conversation["id"] == first
    assert conversation["message_count"] == 2
    assert conversation["history"][0]["content"] == "我想学手冲咖啡"
    assert conversation["decrypt_error"] is False

    # Owner access is not an admin content access → no access log rows.
    assert (
        container.db.scalar("SELECT COUNT(*) AS c FROM content_access_logs") or 0
    ) == 0


async def test_owner_conversation_cross_tenant_404(
    user_api: ApiHelper, container, invite: str
):
    bot = await _bot(user_api)
    cid = await _add(user_api, bot, "私密", HISTORY)
    other_invite = container.invites.create(created_by="system", max_uses=1)["code"]
    await user_api.client.post("/api/auth/logout", headers=user_api.headers)
    await user_api.login("conv-other@example.com", invite=other_invite)

    response, body = await user_api.get(f"/api/bots/{bot['id']}/conversations")
    assert response.status == 404
    response, body = await user_api.get(
        f"/api/bots/{bot['id']}/conversations/{cid}"
    )
    assert response.status == 404
    response, body = await user_api.post(
        f"/api/bots/{bot['id']}/conversations/{cid}/share", json={}
    )
    assert response.status == 404


async def test_owner_unknown_conversation_404(user_api: ApiHelper):
    bot = await _bot(user_api)
    response, body = await user_api.get(
        f"/api/bots/{bot['id']}/conversations/does-not-exist"
    )
    assert response.status == 404


# ---------------------------------------------------------------------------
# sharing
# ---------------------------------------------------------------------------
async def test_share_create_public_access_and_revoke(
    user_api: ApiHelper, container, clock
):
    bot = await _bot(user_api)
    cid = await _add(user_api, bot, "咖啡入门", HISTORY)

    response, body = await user_api.post(
        f"/api/bots/{bot['id']}/conversations/{cid}/share", json={}
    )
    assert response.status == 200, body
    share = body["data"]["share"]
    token = share["token"]
    assert share["bot_id"] == bot["id"]
    assert share["conversation_id"] == cid
    assert share["expires_at"] == 0
    assert share["url"].endswith(f"/console/share/{token}")
    assert token in share["url"]

    # GET .../share returns the live link; POST is idempotent while valid.
    _, body = await user_api.get(
        f"/api/bots/{bot['id']}/conversations/{cid}/share"
    )
    assert body["data"]["share"]["token"] == token
    _, body = await user_api.post(
        f"/api/bots/{bot['id']}/conversations/{cid}/share", json={}
    )
    assert body["data"]["share"]["token"] == token

    # Public access works without a session and returns the decrypted history.
    await user_api.client.post("/api/auth/logout", headers=user_api.headers)
    response, body = await user_api.get(f"/api/public/conversations/{token}")
    assert response.status == 200, body
    public = body["data"]
    assert public["conversation"]["id"] == cid
    assert public["conversation"]["history"][0]["content"] == "我想学手冲咖啡"
    assert public["share"]["token"] == token
    assert public["share"]["expires_at"] == 0

    # Log back in as the owner and revoke (OTP has a 60s cooldown per email).
    clock.tick(61)
    await user_api.login("user@example.com")
    response, body = await user_api.delete(
        f"/api/bots/{bot['id']}/conversations/{cid}/share"
    )
    assert response.status == 200
    assert body["data"]["revoked"] is True
    _, body = await user_api.get(
        f"/api/bots/{bot['id']}/conversations/{cid}/share"
    )
    assert body["data"]["share"] is None
    response, body = await user_api.get(f"/api/public/conversations/{token}")
    assert response.status == 404


async def test_share_expires_and_unknown_token(user_api: ApiHelper, container, clock):
    bot = await _bot(user_api)
    cid = await _add(user_api, bot, "会过期", HISTORY)
    _, body = await user_api.post(
        f"/api/bots/{bot['id']}/conversations/{cid}/share",
        json={"expires_hours": 1},
    )
    token = body["data"]["share"]["token"]
    assert body["data"]["share"]["expires_at"] == clock.now() + 3600

    clock.tick(3601)
    response, body = await user_api.get(f"/api/public/conversations/{token}")
    assert response.status == 410
    assert body["error"]["code"] == "share_expired"
    # Owner GET treats an expired link as "no live share".
    _, body = await user_api.get(
        f"/api/bots/{bot['id']}/conversations/{cid}/share"
    )
    assert body["data"]["share"] is None

    response, body = await user_api.get(
        "/api/public/conversations/definitely-not-a-token"
    )
    assert response.status == 404


async def test_share_is_scoped_to_its_conversation(
    user_api: ApiHelper, container
):
    bot = await _bot(user_api)
    cid = await _add(user_api, bot, "共享", HISTORY)
    await _add(user_api, bot, "未共享", [{"role": "user", "content": "秘密"}])
    _, body = await user_api.post(
        f"/api/bots/{bot['id']}/conversations/{cid}/share", json={}
    )
    token = body["data"]["share"]["token"]
    public = await user_api.client.get(f"/api/public/conversations/{token}")
    payload = await public.json()
    assert [message["content"] for message in payload["data"]["conversation"]["history"]] == [
        "我想学手冲咖啡",
        "可以先从 V60 和浅烘豆开始",
    ]


async def test_encrypted_conversation_share_decrypts(user_api: ApiHelper, container):
    bot = await _bot(user_api)
    cid = await _add(user_api, bot, "加密", HISTORY)
    # Default tenant encryption is on: the backend stores an ENC1 envelope.
    record = container.conversation_backend.records[cid]
    assert record.content and record.content[0]["content"].startswith("ENC1.")
    _, body = await user_api.post(
        f"/api/bots/{bot['id']}/conversations/{cid}/share", json={}
    )
    token = body["data"]["share"]["token"]
    response, body = await user_api.get(f"/api/public/conversations/{token}")
    assert response.status == 200
    assert body["data"]["conversation"]["history"][0]["content"] == "我想学手冲咖啡"
    assert body["data"]["conversation"]["decrypt_error"] is False
