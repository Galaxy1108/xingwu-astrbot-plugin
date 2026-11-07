"""Password login / reset / e-mail binding / username profile acceptance."""

from __future__ import annotations

import pytest

from conftest import ApiHelper
from saas.auth.passwords import (
    PBKDF2_ITERATIONS,
    hash_password,
    needs_rehash,
    verify_password,
)
from saas.errors import AppError

PASSWORD = "secret123"


# --------------------------------------------------------------------------
# unit: password hashing
# --------------------------------------------------------------------------
def test_password_hash_format_and_constant_time_verify():
    encoded = hash_password(PASSWORD)
    parts = encoded.split("$")
    assert parts[0] == "pbkdf2_sha256"
    assert int(parts[1]) == PBKDF2_ITERATIONS
    assert encoded != hash_password(PASSWORD)  # random salt
    assert verify_password(PASSWORD, encoded) is True
    assert verify_password("wrong", encoded) is False
    assert verify_password(PASSWORD, "garbage") is False
    assert verify_password("", encoded) is False
    assert needs_rehash(encoded) is False

    weak = hash_password(PASSWORD, iterations=1)
    assert needs_rehash(weak) is True
    assert verify_password(PASSWORD, weak) is True


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
async def _register(
    api: ApiHelper,
    invite: str,
    *,
    username: str = "alice",
    password: str = PASSWORD,
    display_name: str | None = None,
):
    payload = {
        "invite": invite,
        "username": username,
        "password": password,
    }
    if display_name is not None:
        payload["display_name"] = display_name
    response, body = await api.post("/api/auth/password/register", json=payload)
    return response, body


async def _logout(api: ApiHelper) -> None:
    await api.client.post("/api/auth/logout", headers=api.headers)


def _new_invite(container) -> str:
    return container.invites.create(created_by="system", max_uses=1)["code"]


async def _make_password_user(container, *, username="alice", email=None):
    invite = _new_invite(container)
    return container.auth.register_with_password(
        invite=invite,
        username=username,
        password=PASSWORD,
        display_name=username,
        ip="127.0.0.1",
    )


# --------------------------------------------------------------------------
# registration + login
# --------------------------------------------------------------------------
async def test_password_register_creates_placeholder_account(
    api: ApiHelper, container, invite: str
):
    response, body = await _register(api, invite, display_name="爱丽丝")
    assert response.status == 200, body
    data = body["data"]
    user = data["user"]
    assert user["username"] == "alice"
    assert user["email"] == ""
    assert user["display_name"] == "爱丽丝"
    assert user["email_verified"] is False
    assert user["has_password"] is True
    assert user["recovery_available"] is False
    assert data["csrf_token"]
    assert data["recovery_available"] is False

    row = container.db.query_one("SELECT * FROM users WHERE username = 'alice'")
    assert row["email"].endswith("@no-email.local")
    assert row["password_hash"].startswith("pbkdf2_sha256$")
    assert "secret123" not in row["password_hash"]
    invite_row = container.db.query_one("SELECT * FROM invites")
    assert invite_row["used_count"] == 1
    assert container.audit.list(action="auth.register")["total"] >= 1

    response, me = await api.get("/api/me")
    assert response.status == 200
    assert me["data"]["user"]["username"] == "alice"
    assert me["data"]["user"]["email"] == ""
    assert me["data"]["user"]["has_password"] is True


async def test_password_register_validation_and_invite(
    api: ApiHelper, container, invite: str
):
    # Missing invite → 410 invite_invalid.
    response, body = await api.post(
        "/api/auth/password/register",
        json={"username": "alice", "password": PASSWORD},
    )
    assert response.status == 410
    assert body["error"]["code"] == "invite_invalid"

    # Invalid username.
    response, body = await _register(api, invite, username="ab")
    assert response.status == 400
    assert body["error"]["field"] == "username"
    assert container.invites.verify(invite)  # not consumed on validation failure

    # Too-short password.
    response, body = await _register(api, invite, password="123")
    assert response.status == 400
    assert body["error"]["field"] == "password"

    # Valid registration, then duplicate username on a fresh invite.
    response, body = await _register(api, invite)
    assert response.status == 200, body
    await _logout(api)
    unused_invite = _new_invite(container)
    response, body = await _register(api, unused_invite, username="alice")
    assert response.status == 409
    assert body["error"]["code"] == "username_taken"

    # The second failed attempt did not consume its invite.
    row = container.db.query_one(
        "SELECT * FROM invites WHERE substr(code_hint, 1, 8) = ?",
        (unused_invite[:8],),
    )
    assert row["used_count"] == 0


async def test_password_login_by_username_email_and_errors(
    api: ApiHelper, container, invite: str
):
    await _register(api, invite, username="bob")
    await _logout(api)

    response, body = await api.post(
        "/api/auth/password/login",
        json={"identifier": "bob", "password": PASSWORD},
    )
    assert response.status == 200, body
    assert body["data"]["user"]["username"] == "bob"
    assert body["data"]["csrf_token"]
    response, me = await api.get("/api/me")
    assert response.status == 200

    await _logout(api)

    # Wrong password and unknown identifier are indistinguishable.
    for payload in (
        {"identifier": "bob", "password": "wrong-password"},
        {"identifier": "nobody", "password": PASSWORD},
    ):
        response, body = await api.post("/api/auth/password/login", json=payload)
        assert response.status == 401
        assert body["error"]["code"] == "invalid_credentials"

    # OTP account without a password → password_not_set (400).
    user = container.auth.create_user("nopass@example.com")
    response, body = await api.post(
        "/api/auth/password/login",
        json={"identifier": "nopass@example.com", "password": PASSWORD},
    )
    assert response.status == 400
    assert body["error"]["code"] == "password_not_set"
    assert user["email_verified"] == 1


async def test_banned_user_can_password_login_but_is_gated(
    api: ApiHelper, container, invite: str
):
    response, body = await _register(api, invite, username="banned")
    user_id = body["data"]["user"]["id"]
    container.auth.set_user_status(user_id, "disabled", reason="测试封禁")
    await _logout(api)

    response, body = await api.post(
        "/api/auth/password/login",
        json={"identifier": "banned", "password": PASSWORD},
    )
    assert response.status == 200, body
    assert body["data"]["user"]["status"] == "disabled"
    assert body["data"]["user"]["status_reason"] == "测试封禁"

    response, body = await api.get("/api/me")
    assert response.status == 200
    assert body["data"]["user"]["status"] == "disabled"

    response, body = await api.get("/api/bots")
    assert response.status == 403
    assert body["error"]["code"] == "account_banned"


# --------------------------------------------------------------------------
# password reset
# --------------------------------------------------------------------------
async def test_password_reset_request_and_reset(api: ApiHelper, container):
    user = container.auth.create_user("reset@example.com")
    container.auth.set_password(user["id"], PASSWORD)
    old_session = container.sessions.create(user)

    # Unknown address → generic 200 without an OTP.
    response, body = await api.post(
        "/api/auth/password/reset/request", json={"email": "ghost@example.com"}
    )
    assert response.status == 200
    assert body["data"]["sent"] is True
    assert "dev_code" not in body["data"]
    assert (
        container.db.query_one(
            "SELECT 1 AS ok FROM otp_codes WHERE email = 'ghost@example.com'"
        )
        is None
    )

    response, body = await api.post(
        "/api/auth/password/reset/request", json={"email": "reset@example.com"}
    )
    assert response.status == 200, body
    assert body["data"]["sent"] is True
    code = body["data"]["dev_code"]

    response, body = await api.post(
        "/api/auth/password/reset",
        json={"email": "reset@example.com", "code": "000000", "password": "newpass123"},
    )
    assert response.status == 401
    assert body["error"]["code"] == "otp_invalid"

    response, body = await api.post(
        "/api/auth/password/reset",
        json={"email": "reset@example.com", "code": code, "password": "newpass123"},
    )
    assert response.status == 200, body
    assert body["data"]["reset"] is True

    # All existing sessions are revoked; old password no longer works.
    assert container.sessions.resolve(old_session["token"]) is None
    response, body = await api.post(
        "/api/auth/password/login",
        json={"identifier": "reset@example.com", "password": PASSWORD},
    )
    assert response.status == 401
    response, body = await api.post(
        "/api/auth/password/login",
        json={"identifier": "reset@example.com", "password": "newpass123"},
    )
    assert response.status == 200, body
    assert container.audit.list(action="auth.password_reset")["total"] == 1


async def test_reset_request_not_sent_for_placeholder_email(api: ApiHelper, container):
    created = await _make_password_user(container, username="noemail")
    user_id = created["user"]["id"]
    response, body = await api.post(
        "/api/auth/password/reset/request", json={"email": "noemail@example.com"}
    )
    assert response.status == 200
    assert body["data"]["sent"] is True
    assert "dev_code" not in body["data"]
    assert (
        container.db.query_one(
            "SELECT 1 AS ok FROM otp_codes WHERE email = ? ", (f"{user_id}@no-email.local",)
        )
        is None
    )


# --------------------------------------------------------------------------
# e-mail bind
# --------------------------------------------------------------------------
async def test_email_bind_flow_and_recovery(api: ApiHelper, container, invite: str):
    await _register(api, invite, username="binder")
    response, body = await api.post(
        "/api/auth/email/bind/request", json={"email": "binder@example.com"}
    )
    assert response.status == 200, body
    assert body["data"]["sent"] is True
    code = body["data"]["dev_code"]

    response, body = await api.post(
        "/api/auth/email/bind",
        json={"email": "binder@example.com", "code": "000000"},
    )
    assert response.status == 401
    assert body["error"]["code"] == "otp_invalid"

    response, body = await api.post(
        "/api/auth/email/bind",
        json={"email": "binder@example.com", "code": code},
    )
    assert response.status == 200, body
    user = body["data"]["user"]
    assert user["email"] == "binder@example.com"
    assert user["email_verified"] is True
    assert user["recovery_available"] is True
    assert container.audit.list(action="user.email_bound")["total"] == 1

    # The verified address can now be used for login and reset.
    response, body = await api.post(
        "/api/auth/password/login",
        json={"identifier": "binder@example.com", "password": PASSWORD},
    )
    assert response.status == 200, body
    response, body = await api.post(
        "/api/auth/password/reset/request", json={"email": "binder@example.com"}
    )
    assert response.status == 200
    assert body["data"]["sent"] is True
    assert body["data"]["dev_code"]


async def test_email_bind_rejects_taken_address(user_api: ApiHelper, container, invite: str):
    # ``user_api`` already owns user@example.com; another account cannot bind it.
    response, body = await user_api.post(
        "/api/auth/email/bind/request", json={"email": "taken@example.com"}
    )
    assert response.status == 200, body
    # Occupy the address for a different account.
    other = container.auth.create_user("taken@example.com")
    response, body = await user_api.post(
        "/api/auth/email/bind/request", json={"email": "taken@example.com"}
    )
    assert response.status == 409
    assert body["error"]["code"] == "email_taken"
    assert other["email"] == "taken@example.com"


# --------------------------------------------------------------------------
# /api/me/password + profile
# --------------------------------------------------------------------------
async def test_set_password_requires_current_password(api: ApiHelper, container, invite: str):
    await _register(api, invite, username="changer")

    response, body = await api.post(
        "/api/me/password", json={"new_password": "newpass123"}
    )
    assert response.status == 400
    response, body = await api.post(
        "/api/me/password",
        json={"current_password": "wrong", "new_password": "newpass123"},
    )
    assert response.status == 400
    assert body["error"]["code"] == "invalid_credentials"

    response, body = await api.post(
        "/api/me/password",
        json={"current_password": PASSWORD, "new_password": "newpass123"},
    )
    assert response.status == 200, body
    assert body["data"]["user"]["has_password"] is True
    assert container.audit.list(action="user.password_changed")["total"] == 1

    await _logout(api)
    response, body = await api.post(
        "/api/auth/password/login",
        json={"identifier": "changer", "password": "newpass123"},
    )
    assert response.status == 200, body


async def test_set_password_without_existing_password(user_api: ApiHelper):
    response, body = await user_api.post(
        "/api/me/password", json={"new_password": "brandnew123"}
    )
    assert response.status == 200, body
    assert body["data"]["user"]["has_password"] is True


async def test_profile_username_update_and_conflicts(
    api: ApiHelper, container, invite: str
):
    await _register(api, invite, username="alice")
    response, body = await api.patch(
        "/api/me/profile", json={"username": "alice_new", "display_name": "Alice"}
    )
    assert response.status == 200, body
    assert body["data"]["user"]["username"] == "alice_new"
    assert body["data"]["user"]["display_name"] == "Alice"

    response, body = await api.patch("/api/me/profile", json={"username": "ab"})
    assert response.status == 400
    response, body = await api.patch(
        "/api/me/profile", json={"email": "hacked@example.com"}
    )
    assert response.status == 200
    assert body["data"]["user"]["email"] == ""  # cannot change e-mail here

    # Another account owns "bob" → conflict.
    container.auth.register_with_password(
        invite=_new_invite(container), username="bob", password=PASSWORD
    )
    response, body = await api.patch("/api/me/profile", json={"username": "bob"})
    assert response.status == 409
    assert body["error"]["code"] == "username_taken"


# --------------------------------------------------------------------------
# OTP registration gains optional password/username
# --------------------------------------------------------------------------
async def test_otp_verify_can_set_password_and_username(
    api: ApiHelper, container, invite: str
):
    response = await api.client.post(
        "/api/auth/otp/request",
        json={"email": "otp-pass@example.com", "invite": invite},
    )
    body = await response.json()
    assert response.status == 200, body
    code = body["data"]["dev_code"]
    response = await api.client.post(
        "/api/auth/otp/verify",
        json={
            "email": "otp-pass@example.com",
            "code": code,
            "invite": invite,
            "username": "otpuser",
            "password": PASSWORD,
        },
    )
    body = await response.json()
    assert response.status == 200, body
    assert body["data"]["user"]["username"] == "otpuser"
    assert body["data"]["user"]["has_password"] is True
    assert body["data"]["user"]["email_verified"] is True
    assert body["data"]["user"]["recovery_available"] is True

    await _logout(api)
    response, body = await api.post(
        "/api/auth/password/login",
        json={"identifier": "otpuser", "password": PASSWORD},
    )
    assert response.status == 200, body


async def test_otp_generated_usernames_get_suffix_on_conflict(
    api: ApiHelper, container, invite: str
):
    first = container.auth.create_user("same@example.com")
    assert first["username"] == "same"
    second = container.auth.create_user("same@other.example")
    assert second["username"].startswith("same_")
    assert second["username"] != "same"


# --------------------------------------------------------------------------
# OTP purpose isolation
# --------------------------------------------------------------------------
def test_otp_purpose_isolation(container):
    login = container.otp.request("purpose@example.com", purpose="login")
    reset = container.otp.request("purpose@example.com", purpose="reset")
    bind = container.otp.request("purpose@example.com", purpose="bind")
    assert login["code"] != reset["code"]

    # A code from another purpose never verifies.
    for code, purpose in (
        (login["code"], "reset"),
        (reset["code"], "bind"),
        (bind["code"], "login"),
    ):
        with pytest.raises(AppError):
            container.otp.verify("purpose@example.com", code, purpose=purpose)

    container.otp.verify("purpose@example.com", login["code"], purpose="login")
    container.otp.verify("purpose@example.com", reset["code"], purpose="reset")
    container.otp.verify("purpose@example.com", bind["code"], purpose="bind")
