"""Pre-Bot QR sessions: no bots row until confirmed, temp platform cleanup."""

from __future__ import annotations

import json

import pytest

from conftest import ApiHelper
from saas.errors import AppError
from saas.web.routes_qr_sessions import qr_sessions_of


async def _user(container, invite: str, email: str = "qr-new@example.com") -> dict:
    code = container.auth.request_otp(email, invite=invite)["dev_code"]
    return container.auth.verify_otp(email, code, invite=invite)["user"]


def _template(container) -> dict:
    return container.templates.list(enabled_only=True)[0]


async def _session(container, user: dict, template: dict, name: str = "扫码新流程"):
    return await qr_sessions_of(container).create_session(
        user_id=user["id"],
        platform="weixin_oc",
        name=name,
        template_id=template["id"],
    )


def _bot_rows(container, user_id: str) -> list[dict]:
    return container.db.query(
        "SELECT * FROM bots WHERE user_id = ? AND status != 'deleted'", (user_id,)
    )


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------
async def test_create_session_does_not_create_bot(container, invite, clock):
    user = await _user(container, invite)
    template = _template(container)
    data = await _session(container, user, template)

    assert data["session"]["status"] == "pending"
    assert data["session"]["name"] == "扫码新流程"
    assert data["session"]["platform"] == "weixin_oc"
    assert data["qr"]["qr_content"]
    assert data["qr"]["qr_image"].startswith("data:image/png;base64,")
    assert data["qr"]["expires_at"] == clock.now() + container.settings.qr_ttl_seconds

    # The whole point: no bots row, no list entry, no statistics count.
    assert _bot_rows(container, user["id"]) == []
    assert container.bots.list_for_user(user["id"]) == []
    assert container.bots.count_for_user(user["id"]) == 0

    temp_id = data["session"]["temp_platform_id"]
    assert temp_id.startswith("qrs_")
    assert container.port.state.platforms[temp_id]["type"] == "weixin_oc"
    assert container.port.state.platforms[temp_id]["enable"] is False
    row = container.db.query_one(
        "SELECT * FROM qr_sessions WHERE id = ?", (data["session"]["id"],)
    )
    assert row["status"] == "pending" and row["temp_platform_id"] == temp_id


async def test_poll_scanned_confirmed_and_finalize(container, invite, clock):
    user = await _user(container, invite)
    template = _template(container)
    data = await _session(container, user, template)
    session_id = data["session"]["id"]
    temp_id = data["session"]["temp_platform_id"]
    service = qr_sessions_of(container)

    container.port.simulate_scan(temp_id)
    polled = await service.poll(user_id=user["id"], session_id=session_id)
    assert polled["session"]["status"] == "scanned"

    container.port.simulate_scan_complete(temp_id)
    polled = await service.poll(user_id=user["id"], session_id=session_id)
    assert polled["session"]["status"] == "confirmed"
    # Still no Bot until finalize.
    assert _bot_rows(container, user["id"]) == []

    bot = await service.finalize(user_id=user["id"], session_id=session_id)
    assert bot["status"] == "ready"
    assert bot["bound"] is True
    assert bot["name"] == "扫码新流程"
    assert bot["memory_db"].startswith("memory/")
    assert len(_bot_rows(container, user["id"])) == 1

    # Temporary platform + session are gone.
    assert temp_id not in container.port.state.platforms
    assert container.db.query_one(
        "SELECT * FROM qr_sessions WHERE id = ?", (session_id,)
    ) is None
    assert container.port.state.platforms[bot["id"]]["enable"] is True
    assert container.port.state.platforms[bot["id"]]["weixin_oc_token"].startswith("tok_")

    # Credentials are sealed in bot_bindings.
    binding = container.db.query_one(
        "SELECT credential_cipher FROM bot_bindings WHERE bot_id = ?", (bot["id"],)
    )
    assert binding and bytes(binding["credential_cipher"])[:1] != b"{"
    # Audit trail includes both the creation and the QR session finalize.
    assert container.audit.list(action="bot.created", target_id=bot["id"])["total"] == 1
    assert (
        container.audit.list(action="qr_session.finalized", target_id=bot["id"])["total"]
        == 1
    )


async def test_finalize_requires_confirmation(container, invite):
    user = await _user(container, invite)
    template = _template(container)
    data = await _session(container, user, template)
    with pytest.raises(AppError) as info:
        await qr_sessions_of(container).finalize(
            user_id=user["id"], session_id=data["session"]["id"]
        )
    assert info.value.code == "qr_not_ready"
    assert info.value.status == 409
    assert _bot_rows(container, user["id"]) == []


async def test_cancel_cleans_temp_platform(container, invite):
    user = await _user(container, invite)
    template = _template(container)
    data = await _session(container, user, template)
    session_id = data["session"]["id"]
    temp_id = data["session"]["temp_platform_id"]
    service = qr_sessions_of(container)

    await service.cancel(user_id=user["id"], session_id=session_id)
    assert temp_id not in container.port.state.platforms
    assert container.db.query_one(
        "SELECT * FROM qr_sessions WHERE id = ?", (session_id,)
    ) is None
    assert _bot_rows(container, user["id"]) == []
    with pytest.raises(AppError) as info:
        await service.poll(user_id=user["id"], session_id=session_id)
    assert info.value.status == 404


async def test_expired_session_cleans_up(container, invite, clock):
    user = await _user(container, invite)
    template = _template(container)
    data = await _session(container, user, template)
    session_id = data["session"]["id"]
    temp_id = data["session"]["temp_platform_id"]

    clock.tick(container.settings.qr_idle_timeout_seconds + 1)
    polled = await qr_sessions_of(container).poll(
        user_id=user["id"], session_id=session_id
    )
    assert polled["session"]["status"] == "expired"
    assert temp_id not in container.port.state.platforms
    assert _bot_rows(container, user["id"]) == []
    row = container.db.query_one(
        "SELECT status FROM qr_sessions WHERE id = ?", (session_id,)
    )
    assert row["status"] == "expired"


async def test_gc_expires_stale_sessions(container, invite, clock):
    user = await _user(container, invite)
    template = _template(container)
    data = await _session(container, user, template)
    session_id = data["session"]["id"]
    temp_id = data["session"]["temp_platform_id"]

    clock.tick(container.settings.qr_idle_timeout_seconds + 1)
    cleaned = await qr_sessions_of(container).gc()
    assert cleaned == 1
    assert temp_id not in container.port.state.platforms
    row = container.db.query_one(
        "SELECT status FROM qr_sessions WHERE id = ?", (session_id,)
    )
    assert row["status"] == "expired"
    assert _bot_rows(container, user["id"]) == []


async def test_validation_quota_and_cross_tenant(container, invite):
    user = await _user(container, invite, "qr-owner@example.com")
    template = _template(container)
    service = qr_sessions_of(container)

    with pytest.raises(AppError) as info:
        await service.create_session(
            user_id=user["id"],
            platform="telegram",
            name="x",
            template_id=template["id"],
        )
    assert info.value.field == "platform"
    with pytest.raises(AppError) as info:
        await service.create_session(
            user_id=user["id"],
            platform="weixin_oc",
            name="",
            template_id=template["id"],
        )
    assert info.value.field == "name"

    container.templates.disable(template["id"])
    with pytest.raises(AppError) as info:
        await service.create_session(
            user_id=user["id"],
            platform="weixin_oc",
            name="下架模板",
            template_id=template["id"],
        )
    assert info.value.code == "template_disabled"

    # Quota is checked before creating a temporary platform.
    container.templates.update(template["id"], {"enabled": True})
    container.db.execute(
        "UPDATE quotas SET max_bots = 1 WHERE user_id = ?", (user["id"],)
    )
    await container.bots.create(
        user_id=user["id"],
        name="已有 Bot",
        template_id=template["id"],
        platform="weixin_oc",
    )
    before = set(container.port.state.platforms)
    with pytest.raises(AppError) as info:
        await service.create_session(
            user_id=user["id"],
            platform="weixin_oc",
            name="超配",
            template_id=template["id"],
        )
    assert info.value.code == "quota_exceeded"
    assert set(container.port.state.platforms) == before  # no leaked temp platform

    # Cross-tenant poll/finalize is a 404.
    other_invite = container.invites.create(created_by="system")["code"]
    other = await _user(container, other_invite, "qr-other@example.com")
    container.db.execute(
        "UPDATE quotas SET max_bots = 3 WHERE user_id = ?", (user["id"],)
    )
    data = await _session(container, user, template)
    with pytest.raises(AppError) as info:
        await service.poll(user_id=other["id"], session_id=data["session"]["id"])
    assert info.value.status == 404


async def test_finalize_failure_rolls_back_bot(container, invite):
    user = await _user(container, invite)
    template = _template(container)
    data = await _session(container, user, template)
    session_id = data["session"]["id"]
    container.port.simulate_scan_complete(data["session"]["temp_platform_id"])
    await qr_sessions_of(container).poll(user_id=user["id"], session_id=session_id)

    container.port.fail_on = {"apply_credentials"}
    with pytest.raises(AppError) as info:
        await qr_sessions_of(container).finalize(
            user_id=user["id"], session_id=session_id
        )
    assert info.value.code == "qr_finalize_failed"
    assert _bot_rows(container, user["id"]) == []

    # Session survives for a retry; retry (without the injected failure) works.
    container.port.fail_on = set()
    bot = await qr_sessions_of(container).finalize(
        user_id=user["id"], session_id=session_id
    )
    assert bot["status"] == "ready"
    assert len(_bot_rows(container, user["id"])) == 1


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
async def test_qr_session_http_flow(user_api: ApiHelper, container):
    _, body = await user_api.get("/api/templates")
    template_id = body["data"]["items"][0]["id"]

    response, body = await user_api.post(
        "/api/qr/sessions",
        json={
            "platform": "weixin_oc",
            "name": "HTTP 新流程",
            "template_id": template_id,
        },
    )
    assert response.status == 201, body
    session = body["data"]["session"]
    session_id = session["id"]
    assert session["status"] == "pending"
    assert body["data"]["qr"]["qr_content"]
    _, bots_body = await user_api.get("/api/bots")
    assert bots_body["data"]["items"] == []

    response, body = await user_api.get(f"/api/qr/sessions/{session_id}")
    assert response.status == 200
    assert body["data"]["session"]["id"] == session_id
    response, body = await user_api.get(f"/api/qr/sessions/{session_id}/poll")
    assert response.status == 200
    assert body["data"]["session"]["status"] == "pending"

    response, body = await user_api.post(
        f"/api/dev/qr-sessions/{session_id}/confirm", json={}
    )
    assert response.status == 200, body
    response, body = await user_api.get(f"/api/qr/sessions/{session_id}/poll")
    assert body["data"]["session"]["status"] == "confirmed"

    response, body = await user_api.post(f"/api/qr/sessions/{session_id}/finalize")
    assert response.status == 200, body
    bot = body["data"]["bot"]
    assert bot["status"] == "ready" and bot["bound"] is True
    _, bots_body = await user_api.get("/api/bots")
    assert [item["id"] for item in bots_body["data"]["items"]] == [bot["id"]]

    # Session is gone after finalize.
    response, body = await user_api.get(f"/api/qr/sessions/{session_id}/poll")
    assert response.status == 404


async def test_qr_session_http_cancel(user_api: ApiHelper, container):
    _, body = await user_api.get("/api/templates")
    template_id = body["data"]["items"][0]["id"]
    _, body = await user_api.post(
        "/api/qr/sessions",
        json={"platform": "weixin_oc", "name": "取消", "template_id": template_id},
    )
    session_id = body["data"]["session"]["id"]
    temp_id = body["data"]["session"]["temp_platform_id"]
    response, body = await user_api.delete(f"/api/qr/sessions/{session_id}")
    assert response.status == 200
    assert temp_id not in container.port.state.platforms
    _, bots_body = await user_api.get("/api/bots")
    assert bots_body["data"]["items"] == []
    # Cross-tenant access is a 404.
    response, body = await user_api.get(f"/api/qr/sessions/{session_id}/poll")
    assert response.status == 404


async def test_qr_session_http_cross_tenant_404(user_api: ApiHelper, container, invite):
    _, body = await user_api.get("/api/templates")
    template_id = body["data"]["items"][0]["id"]
    _, body = await user_api.post(
        "/api/qr/sessions",
        json={"platform": "weixin_oc", "name": "A", "template_id": template_id},
    )
    session_id = body["data"]["session"]["id"]
    other_invite = container.invites.create(created_by="system", max_uses=1)["code"]
    await user_api.client.post("/api/auth/logout", headers=user_api.headers)
    await user_api.login("qr-http-other@example.com", invite=other_invite)
    response, body = await user_api.get(f"/api/qr/sessions/{session_id}/poll")
    assert response.status == 404
    response, body = await user_api.post(f"/api/qr/sessions/{session_id}/finalize")
    assert response.status == 404

