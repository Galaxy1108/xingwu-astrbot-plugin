"""Admin-configurable GitHub OAuth settings (dynamic, encrypted at rest)."""

from __future__ import annotations

import json

import pytest

from conftest import ApiHelper
from saas.auth.oauth import OAUTH_SECRET_MASK, OAUTH_SETTINGS_KEY
from saas.settings_store import SettingsStore


class RecordingOAuthClient:
    def __init__(self) -> None:
        self.seen: list[object] = []
        self.redirects: list[str] = []
        self.identity = {
            "subject": "4242",
            "login": "octocat",
            "email": "octocat@example.com",
        }

    async def exchange_code(
        self, provider, code, settings, *, redirect_uri=""  # noqa: ANN001
    ) -> str:
        self.seen.append(settings)
        self.redirects.append(redirect_uri)
        return "token-for-code"

    async def fetch_identity(self, provider, access_token, settings):  # noqa: ANN001
        self.seen.append(settings)
        return dict(self.identity)


def _stored_settings(container) -> dict:
    value = container.settings_store.get(OAUTH_SETTINGS_KEY)
    return value if isinstance(value, dict) else {}


def _decrypted_row(container) -> dict:
    row = container.db.query_one(
        "SELECT value_cipher FROM platform_settings WHERE key = ?",
        (OAUTH_SETTINGS_KEY,),
    )
    assert row is not None
    blob = bytes(row["value_cipher"])
    raw = container.key_manager.unwrap(blob, aad=SettingsStore.aad(OAUTH_SETTINGS_KEY))
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# defaults + mask / keep / clear / deep merge
# ---------------------------------------------------------------------------
async def test_default_disabled_and_callback_derived(admin_api: ApiHelper):
    response, body = await admin_api.get("/api/admin/settings/oauth")
    assert response.status == 200
    github = body["data"]["github"]
    assert github["enabled"] is False
    assert github["client_id"] == ""
    assert github["client_secret"] == ""
    assert github["redirect_uri"] == ""
    assert github["has_secret"] is False
    assert github["callback_url"].endswith("/api/auth/oauth/github/callback")
    assert github["callback_url"].startswith("http://")


async def test_put_enables_provider_and_masks_secret(admin_api: ApiHelper, container):
    response, body = await admin_api.put(
        "/api/admin/settings/oauth",
        json={
            "github": {
                "client_id": "cid-123",
                "client_secret": "super-secret-value",
                "redirect_uri": "https://example.com/cb",
            }
        },
    )
    assert response.status == 200, body
    github = body["data"]["github"]
    assert github["enabled"] is True
    assert github["client_id"] == "cid-123"
    assert github["client_secret"] == OAUTH_SECRET_MASK
    assert github["has_secret"] is True
    assert github["redirect_uri"] == "https://example.com/cb"
    assert github["callback_url"] == "https://example.com/cb"

    # Secret is encrypted at rest and never stored as plaintext.
    row = container.db.query_one(
        "SELECT value_cipher FROM platform_settings WHERE key = ?",
        (OAUTH_SETTINGS_KEY,),
    )
    blob = bytes(row["value_cipher"])
    assert b"super-secret-value" not in blob
    assert _decrypted_row(container)["client_secret"] == "super-secret-value"

    # Provider flips immediately without a restart.
    response, body = await admin_api.get("/api/auth/oauth/providers")
    assert response.status == 200
    assert body["data"]["providers"][0]["enabled"] is True

    # Masked PUT keeps the stored secret untouched.
    response, body = await admin_api.put(
        "/api/admin/settings/oauth",
        json={"github": {"client_secret": OAUTH_SECRET_MASK, "client_id": "cid-456"}},
    )
    assert response.status == 200
    assert body["data"]["github"]["has_secret"] is True
    assert _stored_settings(container)["client_secret"] == "super-secret-value"
    assert _stored_settings(container)["client_id"] == "cid-456"
    assert _stored_settings(container)["redirect_uri"] == "https://example.com/cb"


async def test_put_partial_merge_and_clear_secret(admin_api: ApiHelper, container):
    await admin_api.put(
        "/api/admin/settings/oauth",
        json={
            "github": {
                "client_id": "cid",
                "client_secret": "sec",
                "redirect_uri": "https://a.example/cb",
            }
        },
    )
    # Only redirect changes; client id/secret survive (deep merge).
    response, body = await admin_api.put(
        "/api/admin/settings/oauth",
        json={"github": {"redirect_uri": "https://b.example/cb"}},
    )
    github = body["data"]["github"]
    assert github["client_id"] == "cid"
    assert github["has_secret"] is True
    assert github["redirect_uri"] == "https://b.example/cb"

    # Empty string clears the stored secret → provider disabled again.
    response, body = await admin_api.put(
        "/api/admin/settings/oauth", json={"github": {"client_secret": ""}}
    )
    assert response.status == 200
    github = body["data"]["github"]
    assert github["has_secret"] is False
    assert github["client_secret"] == ""
    assert github["enabled"] is False
    assert "client_secret" not in _stored_settings(container)
    _, providers = await admin_api.get("/api/auth/oauth/providers")
    assert providers["data"]["providers"][0]["enabled"] is False

    # Empty client_id also clears the stored override.
    await admin_api.put(
        "/api/admin/settings/oauth", json={"github": {"client_id": ""}}
    )
    assert "client_id" not in _stored_settings(container)


async def test_flat_console_payload_and_enabled_switch(admin_api: ApiHelper):
    # The console sends a flat payload and also masks with ``has_client_secret``.
    response, body = await admin_api.put(
        "/api/admin/settings/oauth",
        json={
            "enabled": True,
            "client_id": "console-cid",
            "client_secret": "console-secret",
            "redirect_uri": "",
        },
    )
    assert response.status == 200
    github = body["data"]["github"]
    assert github["enabled"] is True
    assert github["has_client_secret"] is True
    assert github["has_secret"] is True
    assert github["client_id"] == "console-cid"

    # Explicit admin switch off keeps the credentials but disables login.
    response, body = await admin_api.put(
        "/api/admin/settings/oauth", json={"enabled": False}
    )
    github = body["data"]["github"]
    assert github["enabled"] is False
    assert github["has_client_secret"] is True
    assert github["client_id"] == "console-cid"
    _, providers = await admin_api.get("/api/auth/oauth/providers")
    assert providers["data"]["providers"][0]["enabled"] is False

    # Switch back on restored the provider without re-entering the secret.
    response, body = await admin_api.put(
        "/api/admin/settings/oauth", json={"enabled": True}
    )
    assert body["data"]["github"]["enabled"] is True
    _, providers = await admin_api.get("/api/auth/oauth/providers")
    assert providers["data"]["providers"][0]["enabled"] is True


async def test_callback_url_falls_back_to_request_origin(admin_api: ApiHelper):
    await admin_api.put(
        "/api/admin/settings/oauth",
        json={"github": {"client_id": "cid", "client_secret": "sec"}},
    )
    _, body = await admin_api.get("/api/admin/settings/oauth")
    callback_url = body["data"]["github"]["callback_url"]
    assert callback_url.endswith("/api/auth/oauth/github/callback")
    assert callback_url.startswith("http://")


# ---------------------------------------------------------------------------
# /test endpoint
# ---------------------------------------------------------------------------
async def test_test_endpoint_validates_configuration(admin_api: ApiHelper):
    response, body = await admin_api.post(
        "/api/admin/settings/oauth/test", json={"provider": "github"}
    )
    assert response.status == 400
    assert body["error"]["field"] in {"client_id", "client_secret"}
    assert set(body["error"]["missing"]) >= {"client_id", "client_secret"}

    await admin_api.put(
        "/api/admin/settings/oauth",
        json={"github": {"client_id": "cid", "client_secret": "sec"}},
    )
    response, body = await admin_api.post(
        "/api/admin/settings/oauth/test", json={"provider": "github"}
    )
    assert response.status == 200
    assert body["data"]["enabled"] is True
    assert body["data"]["callback_url"].endswith(
        "/api/auth/oauth/github/callback"
    )

    response, body = await admin_api.post(
        "/api/admin/settings/oauth/test", json={"provider": "gitlab"}
    )
    assert response.status == 400
    assert body["error"]["field"] == "provider"


# ---------------------------------------------------------------------------
# permissions + audit
# ---------------------------------------------------------------------------
async def test_admin_only(user_api: ApiHelper):
    for method, path, payload in (
        ("get", "/api/admin/settings/oauth", None),
        ("put", "/api/admin/settings/oauth", {"github": {"client_id": "x"}}),
        ("post", "/api/admin/settings/oauth/test", {"provider": "github"}),
    ):
        helper = getattr(user_api, method)
        if payload is None:
            response, body = await helper(path)
        else:
            response, body = await helper(path, json=payload)
        assert response.status == 403, (method, path, body)


async def test_audit_never_records_secret(admin_api: ApiHelper, container):
    await admin_api.put(
        "/api/admin/settings/oauth",
        json={
            "github": {
                "client_id": "cid",
                "client_secret": "audit-secret-value",
                "redirect_uri": "https://example.com/cb",
            }
        },
    )
    audit = container.audit.list(action="oauth.settings_updated")
    assert audit["total"] == 1
    item = audit["items"][0]
    assert item["target_id"] == OAUTH_SETTINGS_KEY
    assert item["detail"]["has_secret"] is True
    assert item["detail"]["client_id"] == "cid"
    serialized = json.dumps(item["detail"], ensure_ascii=False)
    assert "audit-secret-value" not in serialized
    assert OAUTH_SECRET_MASK not in serialized


# ---------------------------------------------------------------------------
# OAuthService precedence: settings_store overrides Settings
# ---------------------------------------------------------------------------
def test_store_overrides_settings_per_field(container):
    container.settings.github_client_id = "env-id"
    container.settings.github_client_secret = "env-secret"
    container.settings.github_redirect_uri = ""
    oauth = container.oauth

    assert oauth.github_enabled() is True
    config = oauth.github_config()
    assert config["client_id"] == "env-id"
    assert config["client_secret"] == "env-secret"

    # Store only overrides the secret: client id still falls back to Settings.
    container.settings_store.set(OAUTH_SETTINGS_KEY, {"client_secret": "store-secret"})
    config = oauth.github_config()
    assert config["client_id"] == "env-id"
    assert config["client_secret"] == "store-secret"
    assert oauth.providers()[0]["enabled"] is True

    # Full store override wins over env values.
    container.settings_store.set(
        OAUTH_SETTINGS_KEY,
        {
            "client_id": "store-id",
            "client_secret": "store-secret",
            "redirect_uri": "https://store.example/cb",
        },
    )
    config = oauth.github_config()
    assert config == {
        "client_id": "store-id",
        "client_secret": "store-secret",
        "redirect_uri": "https://store.example/cb",
    }
    started = oauth.start("github", "login", invite="INV-X")
    assert "client_id=store-id" in started["authorize_url"]
    assert "redirect_uri=https%3A%2F%2Fstore.example%2Fcb" in started["authorize_url"]

    # Clearing the store falls back to Settings again (still enabled).
    container.settings_store.delete(OAUTH_SETTINGS_KEY)
    config = oauth.github_config()
    assert config["client_id"] == "env-id"
    assert config["client_secret"] == "env-secret"


async def test_callback_uses_store_credentials(container):
    invite = container.invites.create(created_by="system", max_uses=1)["code"]
    container.settings_store.set(
        OAUTH_SETTINGS_KEY,
        {
            "client_id": "store-id",
            "client_secret": "store-secret",
            "redirect_uri": "https://store.example/cb",
        },
    )
    client = RecordingOAuthClient()
    container.oauth.client = client
    started = container.oauth.start("github", "login", invite=invite)
    result = await container.oauth.callback(
        "github",
        "code-1",
        started["state"],
        callback_url="http://fallback/api/auth/oauth/github/callback",
    )
    assert result["user"]["id"]
    assert client.seen, "exchange/identity should receive settings"
    for seen in client.seen:
        assert getattr(seen, "github_client_id") == "store-id"
        assert getattr(seen, "github_client_secret") == "store-secret"
        assert getattr(seen, "github_redirect_uri") == "https://store.example/cb"
    assert client.redirects == ["https://store.example/cb"]


async def test_disabled_without_any_credentials(container):
    container.settings.github_client_id = ""
    container.settings.github_client_secret = ""
    container.settings_store.delete(OAUTH_SETTINGS_KEY)
    assert container.oauth.github_enabled() is False
    assert container.oauth.providers()[0]["enabled"] is False
    with pytest.raises(Exception):
        container.oauth.start("github", "login")
