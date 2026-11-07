"""GitHub OAuth providers / state / callback / bind / unbind (mocked network)."""

from __future__ import annotations

import pytest

from conftest import ApiHelper
from saas.errors import AppError


class FakeOAuthClient:
    """Deterministic network double; never touches GitHub."""

    def __init__(self) -> None:
        self.identity = {
            "subject": "1001",
            "login": "octocat",
            "email": "octocat@example.com",
        }
        self.exchanges: list[str] = []
        self.fetches: list[str] = []

    async def exchange_code(
        self, provider, code, settings, *, redirect_uri=""  # noqa: ANN001
    ) -> str:
        self.exchanges.append(str(code))
        return f"token-for-{code}"

    async def fetch_identity(self, provider, access_token, settings):  # noqa: ANN001
        self.fetches.append(str(access_token))
        return dict(self.identity)


@pytest.fixture
def oauth_client() -> FakeOAuthClient:
    return FakeOAuthClient()


@pytest.fixture
def oauth_container(container, oauth_client):
    container.settings.github_client_id = "client-id"
    container.settings.github_client_secret = "client-secret"
    container.settings.github_redirect_uri = (
        "http://localhost/api/auth/oauth/github/callback"
    )
    container.oauth.client = oauth_client
    return container


def _new_invite(container) -> str:
    return container.invites.create(created_by="system", max_uses=1)["code"]


def _password_user(container, username="alice"):
    return container.auth.register_with_password(
        invite=_new_invite(container),
        username=username,
        password="secret123",
    )["user"]


# --------------------------------------------------------------------------
# providers + start
# --------------------------------------------------------------------------
def test_providers_reflect_configuration(container):
    assert container.oauth.providers() == [
        {"id": "github", "name": "GitHub", "enabled": False}
    ]
    container.settings.github_client_id = "cid"
    container.settings.github_client_secret = "secret"
    assert container.oauth.providers()[0]["enabled"] is True


def test_start_creates_single_use_state(oauth_container, clock):
    result = oauth_container.oauth.start(
        "github", "login", invite="INV-TEST", redirect="/console/bots"
    )
    assert result["state"]
    assert "github.com/login/oauth/authorize" in result["authorize_url"]
    assert "client-id" in result["authorize_url"]
    assert result["state"] in result["authorize_url"]

    row = oauth_container.db.query_one(
        "SELECT * FROM oauth_states WHERE state = ?", (result["state"],)
    )
    assert row["mode"] == "login"
    assert row["redirect"] == "/console/bots"
    assert int(row["expires_at"]) - clock.now() == 600

    # Open-redirect attempts are dropped (stored as empty).
    unsafe = oauth_container.oauth.start(
        "github", "login", redirect="//evil.example/steal"
    )
    row = oauth_container.db.query_one(
        "SELECT * FROM oauth_states WHERE state = ?", (unsafe["state"],)
    )
    assert row["redirect"] == ""


def test_start_validation(oauth_container, container):
    with pytest.raises(AppError) as info:
        oauth_container.oauth.start("github", "bind")
    assert info.value.status == 401

    with pytest.raises(AppError) as info:
        oauth_container.oauth.start("github", "delete")
    assert info.value.field == "mode"

    with pytest.raises(AppError) as info:
        oauth_container.oauth.start("gitlab", "login")
    assert info.value.field == "provider"

    # Unconfigured provider is disabled.
    container.settings.github_client_id = ""
    with pytest.raises(AppError) as info:
        container.oauth.start("github", "login")
    assert info.value.code == "oauth_disabled"


# --------------------------------------------------------------------------
# callback: login / register
# --------------------------------------------------------------------------
async def test_callback_register_with_invite(oauth_container, oauth_client):
    invite = _new_invite(oauth_container)
    started = oauth_container.oauth.start("github", "register", invite=invite)
    result = await oauth_container.oauth.callback(
        "github", "the-code", started["state"], ip="127.0.0.1"
    )
    assert result["is_new"] is True
    user = result["user"]
    assert user["email"] == ""
    assert user["username"] == "octocat"
    assert user["email_verified"] is False
    assert user["has_password"] is False
    assert result["session"]["token"]
    assert oauth_client.exchanges == ["the-code"]
    assert oauth_client.fetches == ["token-for-the-code"]

    row = oauth_container.db.query_one(
        "SELECT * FROM users WHERE id = ?", (user["id"],)
    )
    assert row["email"].endswith("@no-email.local")
    assert row["password_hash"] == ""
    identity = oauth_container.db.query_one(
        "SELECT * FROM oauth_identities WHERE user_id = ?", (user["id"],)
    )
    assert identity["provider"] == "github"
    assert identity["subject"] == "1001"
    assert identity["login"] == "octocat"
    assert identity["email"] == "octocat@example.com"
    invite_row = oauth_container.db.query_one(
        "SELECT * FROM invites WHERE substr(code_hint, 1, 8) = ?", (invite[:8],)
    )
    assert invite_row["used_count"] == 1

    # The session returned by the callback resolves to the new user.
    resolved = oauth_container.sessions.resolve(result["session"]["token"])
    assert resolved is not None and resolved[0]["id"] == user["id"]


async def test_callback_login_existing_identity(oauth_container):
    invite = _new_invite(oauth_container)
    started = oauth_container.oauth.start("github", "register", invite=invite)
    first = await oauth_container.oauth.callback("github", "c1", started["state"])

    started = oauth_container.oauth.start("github", "login")
    second = await oauth_container.oauth.callback("github", "c2", started["state"])
    assert second["is_new"] is False
    assert second["user"]["id"] == first["user"]["id"]
    assert second["session"]["token"] != first["session"]["token"]


async def test_callback_without_invite_needs_binding(oauth_container):
    started = oauth_container.oauth.start("github", "login")
    with pytest.raises(AppError) as info:
        await oauth_container.oauth.callback("github", "code", started["state"])
    assert info.value.code == "oauth_not_bound"
    assert info.value.status == 400
    assert (
        oauth_container.db.query_one(
            "SELECT 1 AS ok FROM oauth_identities WHERE subject = '1001'"
        )
        is None
    )


async def test_callback_state_is_single_use_and_expires(
    oauth_container, oauth_client, clock
):
    invite = _new_invite(oauth_container)
    started = oauth_container.oauth.start("github", "login", invite=invite)
    await oauth_container.oauth.callback("github", "code", started["state"])
    with pytest.raises(AppError) as info:
        await oauth_container.oauth.callback("github", "code", started["state"])
    assert info.value.code == "oauth_state_invalid"

    started = oauth_container.oauth.start("github", "login")
    clock.tick(601)
    with pytest.raises(AppError) as info:
        await oauth_container.oauth.callback("github", "code", started["state"])
    assert info.value.code == "oauth_state_expired"

    with pytest.raises(AppError) as info:
        await oauth_container.oauth.callback("github", "code", "not-a-state")
    assert info.value.code == "oauth_state_invalid"


# --------------------------------------------------------------------------
# binding
# --------------------------------------------------------------------------
async def test_bind_flow_idempotent_and_conflict(oauth_container, oauth_client):
    alice = _password_user(oauth_container, "alice")
    bob = _password_user(oauth_container, "bob")

    started = oauth_container.oauth.start(
        "github", "bind", user_id=alice["id"], redirect="/console/settings"
    )
    result = await oauth_container.oauth.callback(
        "github", "bind-code", started["state"], current_user_id=alice["id"]
    )
    assert result["bound"] is True
    assert result["mode"] == "bind"
    assert result["next"] == "/console/settings"
    assert oauth_container.oauth.list_identities(alice["id"])[0]["provider"] == "github"
    assert oauth_container.audit.list(action="user.oauth_bound")["total"] == 1

    # Same user + same identity → idempotent.
    again = oauth_container.oauth.start("github", "bind", user_id=alice["id"])
    result = await oauth_container.oauth.callback(
        "github", "bind-code-2", again["state"], current_user_id=alice["id"]
    )
    assert result["bound"] is True

    # Identity already bound to Alice → Bob gets 409.
    conflict = oauth_container.oauth.start("github", "bind", user_id=bob["id"])
    with pytest.raises(AppError) as info:
        await oauth_container.oauth.callback(
            "github", "bind-code-3", conflict["state"], current_user_id=bob["id"]
        )
    assert info.value.code == "oauth_already_bound"
    assert info.value.status == 409


async def test_bind_requires_matching_session(oauth_container):
    alice = _password_user(oauth_container, "alice")
    bob = _password_user(oauth_container, "bob")
    started = oauth_container.oauth.start("github", "bind", user_id=alice["id"])
    with pytest.raises(AppError) as info:
        await oauth_container.oauth.callback(
            "github", "code", started["state"], current_user_id=bob["id"]
        )
    assert info.value.code == "oauth_state_invalid"

    with pytest.raises(AppError) as info:
        await oauth_container.oauth.callback(
            "github", "code", started["state"], current_user_id=""
        )
    assert info.value.status == 400

    # A fresh bind state with no session is rejected as unauthorized.
    started = oauth_container.oauth.start("github", "bind", user_id=alice["id"])
    with pytest.raises(AppError) as info:
        await oauth_container.oauth.callback(
            "github", "code", started["state"], current_user_id=""
        )
    assert info.value.status == 401


# --------------------------------------------------------------------------
# unbind
# --------------------------------------------------------------------------
async def test_unbind_requires_another_login_method(oauth_container):
    invite = _new_invite(oauth_container)
    started = oauth_container.oauth.start("github", "register", invite=invite)
    created = await oauth_container.oauth.callback("github", "code", started["state"])
    user_id = created["user"]["id"]

    with pytest.raises(AppError) as info:
        oauth_container.oauth.unbind(user_id, "github")
    assert info.value.code == "last_login_method"
    assert info.value.status == 400

    # Setting a password gives the account another login method.
    oauth_container.auth.set_password(user_id, "secret123")
    result = oauth_container.oauth.unbind(user_id, "github")
    assert result["unbound"] is True
    assert oauth_container.oauth.list_identities(user_id) == []

    # Unknown provider is rejected; unbound provider is a no-op.
    with pytest.raises(AppError):
        oauth_container.oauth.unbind(user_id, "gitlab")
    assert oauth_container.oauth.unbind(user_id, "github")["unbound"] is False


async def test_unbind_allowed_with_verified_email(oauth_container):
    user = oauth_container.auth.create_user("verified@example.com")
    oauth_container.db.execute(
        "INSERT INTO oauth_identities(id, user_id, provider, subject, email, login, "
        "created_at) VALUES (?,?,?,?,?,?,?)",
        ("oid_test", user["id"], "github", "99", "", "octo", 0),
    )
    result = oauth_container.oauth.unbind(user["id"], "github")
    assert result["unbound"] is True


# --------------------------------------------------------------------------
# HTTP routes
# --------------------------------------------------------------------------
async def test_oauth_http_routes(api: ApiHelper, oauth_container, oauth_client):
    response, body = await api.get("/api/auth/oauth/providers")
    assert response.status == 200
    assert body["data"]["providers"][0]["enabled"] is True

    # Public start returns the JSON authorize URL.
    invite = _new_invite(oauth_container)
    response, body = await api.get(
        f"/api/auth/oauth/github/start?mode=login&invite={invite}&redirect=/console/bots"
    )
    assert response.status == 200
    state = body["data"]["state"]
    assert body["data"]["authorize_url"]

    # Browser-style callback → 302 + session cookie.
    response = await api.client.get(
        f"/api/auth/oauth/github/callback?code=code123&state={state}",
        allow_redirects=False,
    )
    assert response.status == 302
    assert "/console/oauth/callback?ok=1" in response.headers["Location"]
    assert "next=/console/bots" in response.headers["Location"]
    response, me = await api.get("/api/me")
    assert response.status == 200
    assert me["data"]["user"]["username"] == "octocat"

    # JSON-mode failure returns the normal error envelope.
    response = await api.client.get(
        "/api/auth/oauth/github/callback?code=x&state=bad",
        headers={"Accept": "application/json"},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"]["code"] == "oauth_state_invalid"

    # Browser-mode failure redirects with an error code.
    response = await api.client.get(
        "/api/auth/oauth/github/callback?code=x&state=bad",
        allow_redirects=False,
    )
    assert response.status == 302
    assert "error=oauth_state_invalid" in response.headers["Location"]


async def test_oauth_bind_start_requires_login(oauth_container):
    from aiohttp.test_utils import TestClient, TestServer

    from saas.web.app import create_app

    client = TestClient(TestServer(create_app(oauth_container)))
    await client.start_server()
    try:
        anonymous = ApiHelper(client)
        response, body = await anonymous.get(
            "/api/auth/oauth/github/start?mode=bind"
        )
        assert response.status == 401
        assert body["error"]["code"] == "unauthorized"
    finally:
        await client.close()


async def test_oauth_bind_routes(user_api: ApiHelper, oauth_container):
    response, body = await user_api.get("/api/auth/oauth/github/start?mode=bind")
    assert response.status == 200
    state = body["data"]["state"]

    response = await user_api.client.get(
        f"/api/auth/oauth/github/callback?code=bindcode&state={state}",
        allow_redirects=False,
    )
    assert response.status == 302
    assert "ok=1" in response.headers["Location"]

    response, body = await user_api.get("/api/me/oauth")
    assert response.status == 200
    assert [item["provider"] for item in body["data"]["items"]] == ["github"]

    response, body = await user_api.post("/api/me/oauth/github/unbind")
    assert response.status == 200
    assert body["data"]["unbound"] is True
    response, body = await user_api.get("/api/me/oauth")
    assert body["data"]["items"] == []


async def test_oauth_http_callback_json(api: ApiHelper, oauth_container):
    invite = _new_invite(oauth_container)
    response, body = await api.get(
        f"/api/auth/oauth/github/start?mode=register&invite={invite}"
    )
    assert response.status == 200
    state = body["data"]["state"]
    response = await api.client.get(
        f"/api/auth/oauth/github/callback?code=c&state={state}",
        headers={"Accept": "application/json"},
    )
    assert response.status == 200
    body = await response.json()
    assert body["data"]["user"]["username"] == "octocat"
    assert body["data"]["csrf_token"]
