"""FR-A acceptance: one-time invites, OTP rules, sessions, roles."""

from __future__ import annotations

import pytest

from conftest import ApiHelper
from saas.errors import AppError


def _code(container, email: str, invite: str | None = None) -> str:
    """Request an OTP; dev echo gives the plaintext for tests."""
    payload = container.auth.request_otp(email, invite=invite)
    return payload["dev_code"]


def test_invite_is_one_time(container, invite):
    """Using the same invite twice must fail with 410 invite_exhausted."""
    container.auth.verify_otp(
        "a@example.com", _code(container, "a@example.com", invite), invite=invite
    )
    with pytest.raises(AppError) as info:
        container.auth.request_otp("b@example.com", invite=invite)
    assert info.value.status == 410
    assert info.value.code == "invite_exhausted"


def test_invite_expiry(container, invite, clock):
    clock.tick(73 * 3600)
    with pytest.raises(AppError) as info:
        container.invites.verify(invite)
    assert info.value.code == "invite_expired"
    assert info.value.status == 410


def test_invite_revoked(container, invite):
    assert container.invites.revoke(invite)
    with pytest.raises(AppError) as info:
        container.invites.verify(invite)
    assert info.value.code == "invite_invalid"


def test_invite_codes_are_hashed(container, invite):
    row = container.db.query_one("SELECT * FROM invites")
    assert invite not in (row["code_hash"], row["code_hint"])
    assert len(row["code_hash"]) == 64


def test_otp_resend_rate_limit(container, invite):
    container.auth.request_otp("c@example.com", invite=invite)
    with pytest.raises(AppError) as info:
        container.auth.request_otp("c@example.com", invite=invite)
    assert info.value.status == 429
    assert info.value.extra.get("retry_after") == 60


def test_otp_wrong_code_and_attempt_limit(container, invite):
    _code(container, "d@example.com", invite)
    errors = []
    for _ in range(5):
        with pytest.raises(AppError) as info:
            container.auth.verify_otp("d@example.com", "000000", invite=invite)
        errors.append(info.value.code)
    assert errors[:4] == ["otp_invalid"] * 4
    assert errors[4] == "otp_attempts_exceeded"


def test_otp_single_use(container, invite):
    code = _code(container, "e@example.com", invite)
    container.auth.verify_otp("e@example.com", code, invite=invite)
    with pytest.raises(AppError):
        container.auth.verify_otp("e@example.com", code, invite=invite)


def test_otp_expiry(container, invite, clock):
    code = _code(container, "f@example.com", invite)
    clock.tick(601)
    with pytest.raises(AppError) as info:
        container.auth.verify_otp("f@example.com", code, invite=invite)
    assert info.value.code == "otp_invalid"


def test_register_creates_tenant_key_quota_wallet(container, invite):
    code = _code(container, "g@example.com", invite)
    result = container.auth.verify_otp("g@example.com", code, invite=invite)
    user_id = result["user"]["id"]
    assert result["is_new"] is True
    assert container.db.query_one(
        "SELECT 1 AS ok FROM tenant_keys WHERE tenant_id = ?", (user_id,)
    )
    assert container.db.query_one(
        "SELECT max_bots FROM quotas WHERE user_id = ?", (user_id,)
    )["max_bots"] == 3
    assert container.db.query_one(
        "SELECT balance FROM wallets WHERE user_id = ?", (user_id,)
    )["balance"] == 0


def test_disabled_user_is_logged_out(container, invite):
    code = _code(container, "h@example.com", invite)
    result = container.auth.verify_otp("h@example.com", code, invite=invite)
    user_id = result["user"]["id"]
    token = result["session"]["token"]
    container.auth.set_user_status(user_id, "disabled", actor_id="admin")
    assert container.sessions.resolve(token) is None


def test_admin_session_has_12h_ttl(container, clock):
    admin = container.auth.get_user_by_email("admin@example.com")
    session = container.sessions.create(admin)
    assert session["expires_at"] - clock.now() == 12 * 3600
    assert session["absolute_expires_at"] == session["expires_at"]


async def test_api_login_flow_and_me(api: ApiHelper, invite: str):
    data = await api.login("i@example.com", invite=invite)
    assert data["user"]["role"] == "user"
    response, body = await api.get("/api/me")
    assert response.status == 200
    assert body["data"]["user"]["email"] == "i@example.com"
    assert body["data"]["limits"]["max_bots"] == 3


async def test_api_requires_auth(api: ApiHelper):
    response, body = await api.get("/api/bots")
    assert response.status == 401
    assert body["error"]["code"] == "unauthorized"


async def test_api_write_requires_csrf(user_api: ApiHelper):
    response = await user_api.client.post(
        "/api/bots", json={"name": "x", "template_id": "t", "platform": "weixin_oc"}
    )
    body = await response.json()
    assert response.status == 403
    assert body["error"]["code"] == "csrf_invalid"


async def test_admin_routes_forbidden_for_users(user_api: ApiHelper):
    response, body = await user_api.get("/api/admin/users")
    assert response.status == 403
    assert body["error"]["code"] == "forbidden"
