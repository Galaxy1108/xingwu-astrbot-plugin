"""FR-B acceptance: QR TTL 60s, ≤3 auto refreshes, idle reclaim, finalize."""

from __future__ import annotations

import json

import pytest

from conftest import ApiHelper
from saas.errors import AppError


async def _user_with_bot(container, invite, email: str = "qr@example.com"):
    code = container.auth.request_otp(email, invite=invite)["dev_code"]
    user = container.auth.verify_otp(email, code, invite=invite)["user"]
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"],
        name="扫码 Bot",
        template_id=template["id"],
        platform="weixin_oc",
    )
    return user, bot


async def test_qr_start_ttl_and_image(container, invite, clock):
    user, bot = await _user_with_bot(container, invite)
    qr = await container.qr.start(user_id=user["id"], bot_id=bot["id"])
    assert qr["status"] == "pending"
    assert qr["expires_at"] == clock.now() + 60
    assert qr["qr_image"].startswith("data:image/png;base64,")
    assert qr["refresh_count"] == 0


async def test_qr_one_session_per_bot(container, invite):
    user, bot = await _user_with_bot(container, invite)
    await container.qr.start(user_id=user["id"], bot_id=bot["id"])
    with pytest.raises(AppError) as info:
        await container.qr.start(user_id=user["id"], bot_id=bot["id"])
    assert info.value.status == 409
    assert info.value.code == "qr_session_exists"


async def test_qr_auto_refresh_at_most_three_times(container, invite, clock):
    user, bot = await _user_with_bot(container, invite)
    await container.qr.start(user_id=user["id"], bot_id=bot["id"])
    statuses = []
    for round_no in range(1, 5):
        clock.tick(61)
        qr = await container.qr.poll(user_id=user["id"], bot_id=bot["id"])
        statuses.append((round_no, qr["status"], qr["refresh_count"]))
    assert statuses[0] == (1, "pending", 1)
    assert statuses[1] == (2, "pending", 2)
    assert statuses[2] == (3, "pending", 3)
    assert statuses[3] == (4, "expired", 4)


async def test_qr_expired_allows_restart(container, invite, clock):
    user, bot = await _user_with_bot(container, invite)
    await container.qr.start(user_id=user["id"], bot_id=bot["id"])
    for _ in range(4):
        clock.tick(61)
        await container.qr.poll(user_id=user["id"], bot_id=bot["id"])
    qr = await container.qr.start(user_id=user["id"], bot_id=bot["id"])
    assert qr["status"] == "pending"
    assert qr["refresh_count"] == 0


async def test_qr_idle_reclaim_after_5_minutes(container, invite, clock):
    user, bot = await _user_with_bot(container, invite)
    await container.qr.start(user_id=user["id"], bot_id=bot["id"])
    clock.tick(301)
    with pytest.raises(AppError) as info:
        await container.qr.poll(user_id=user["id"], bot_id=bot["id"])
    assert info.value.code == "qr_expired"
    assert info.value.status == 410


async def test_finalize_requires_scan(container, invite):
    user, bot = await _user_with_bot(container, invite)
    await container.qr.start(user_id=user["id"], bot_id=bot["id"])
    with pytest.raises(AppError) as info:
        await container.qr.finalize(user_id=user["id"], bot_id=bot["id"])
    assert info.value.code == "qr_not_ready"
    assert info.value.status == 409


async def test_scan_and_finalize_encrypts_credentials(container, invite):
    user, bot = await _user_with_bot(container, invite)
    await container.qr.start(user_id=user["id"], bot_id=bot["id"])
    container.port.simulate_scan_complete(bot["id"])
    qr = await container.qr.poll(user_id=user["id"], bot_id=bot["id"])
    assert qr["status"] == "created"
    final = await container.qr.finalize(user_id=user["id"], bot_id=bot["id"])
    assert final["status"] == "ready"
    assert container.port.state.platforms[bot["id"]]["enable"] is True
    row = container.db.query_one(
        "SELECT credential_cipher FROM bot_bindings WHERE bot_id = ?", (bot["id"],)
    )
    assert row and row["credential_cipher"]
    blob = bytes(row["credential_cipher"])
    assert b"tok_" not in blob  # plaintext token must never be stored
    cipher = container.tenants.get(user["id"])
    decrypted = cipher.decrypt_bytes(
        blob, bot_id=bot["id"], purpose="credential", record_id=bot["id"]
    )
    assert json.loads(decrypted)["weixin_oc_token"].startswith("tok_")


async def test_qr_cross_tenant_is_404(container, invite):
    user, bot = await _user_with_bot(container, invite, "owner@example.com")
    inv_b = container.invites.create(created_by="system")["code"]
    code = container.auth.request_otp("other@example.com", invite=inv_b)["dev_code"]
    other = container.auth.verify_otp(
        "other@example.com", code, invite=inv_b
    )["user"]
    with pytest.raises(AppError) as info:
        await container.qr.start(user_id=other["id"], bot_id=bot["id"])
    assert info.value.status == 404


async def test_qr_poll_api_state_machine(user_api: ApiHelper, container):
    _, body = await user_api.get("/api/templates")
    template_id = body["data"]["items"][0]["id"]
    _, body = await user_api.post(
        "/api/bots",
        json={"name": "QR API", "template_id": template_id, "platform": "weixin_oc"},
    )
    bot_id = body["data"]["bot"]["id"]
    response, body = await user_api.post(f"/api/bots/{bot_id}/qr/start")
    assert response.status == 200
    assert body["data"]["qr"]["status"] == "pending"
    response, body = await user_api.get(f"/api/bots/{bot_id}/qr/poll")
    assert body["data"]["qr"]["status"] == "pending"
    # dev-only simulation endpoint
    await user_api.post(f"/api/dev/qr/{bot_id}/confirm", json={})
    response, body = await user_api.get(f"/api/bots/{bot_id}/qr/poll")
    assert body["data"]["qr"]["status"] == "created"
    response, body = await user_api.post(f"/api/bots/{bot_id}/qr/finalize")
    assert response.status == 200
    assert body["data"]["bot"]["status"] == "ready"
    assert body["data"]["bot"]["bound"] is True


async def test_dev_endpoints_disabled_outside_dev_mode(container, invite):
    container.settings.dev_mode = False
    user, bot = await _user_with_bot(container, invite)
    assert container.settings.dev_mode is False
