"""HTTP hardening: 401/403/404/CSRF, disabled users, admin boundaries."""

from __future__ import annotations

from conftest import ApiHelper


async def test_unauthenticated_reads_are_401(api: ApiHelper):
    for path in ("/api/me", "/api/bots", "/api/templates", "/api/admin/users"):
        response, body = await api.get(path)
        assert response.status == 401, path
        assert body["error"]["code"] == "unauthorized"


async def test_public_endpoints_are_reachable(api: ApiHelper):
    response, body = await api.get("/api/version")
    assert response.status == 200
    response, body = await api.get("/healthz")
    assert response.status == 200


async def test_csrf_required_on_writes(user_api: ApiHelper):
    response = await user_api.client.patch("/api/bots/nope", json={"name": "x"})
    body = await response.json()
    assert response.status == 403
    assert body["error"]["code"] == "csrf_invalid"


async def test_admin_can_list_users_and_templates(admin_api: ApiHelper):
    response, body = await admin_api.get("/api/admin/users")
    assert response.status == 200
    assert body["data"]["total"] >= 1
    response, body = await admin_api.get("/api/admin/templates")
    assert response.status == 200
    assert body["data"]["items"]
    response, body = await admin_api.get("/api/admin/audit")
    assert response.status == 200
    assert body["data"]["items"]


async def test_admin_can_create_template_and_invite(admin_api: ApiHelper):
    response, body = await admin_api.post(
        "/api/admin/templates",
        json={
            "name": "测试模板",
            "persona_prompt": "你是 {bot_name}",
            "config_patch": {"provider_settings": {}},
            "quota": {"max_bots": 2, "monthly_tokens": 1000, "max_memories": 100},
        },
    )
    assert response.status == 201, body
    template_id = body["data"]["template"]["id"]
    response, body = await admin_api.patch(
        f"/api/admin/templates/{template_id}", json={"enabled": False}
    )
    assert response.status == 200
    assert body["data"]["template"]["enabled"] is False

    response, body = await admin_api.post(
        "/api/admin/invites", json={"max_uses": 1, "ttl_hours": 72}
    )
    assert response.status == 201
    code = body["data"]["invite"]["code"]
    assert code.startswith("INV-")
    response, body = await admin_api.get("/api/admin/invites")
    assert response.status == 200
    assert body["data"]["items"][0]["code_hint"]


async def test_admin_cannot_disable_encryption(admin_api: ApiHelper):
    _, body = await admin_api.get("/api/admin/users")
    user_id = body["data"]["items"][0]["id"]
    response, body = await admin_api.put(
        f"/api/admin/users/{user_id}/encryption", json={"enabled": False}
    )
    assert response.status == 403
    assert body["error"]["code"] == "forbidden"


async def test_disabled_user_session_revoked(
    admin_api: ApiHelper, container, invite: str
):
    """Disabling a user revokes sessions immediately (separate browser client)."""
    from aiohttp.test_utils import TestClient, TestServer

    from saas.web.app import create_app

    other_client = TestClient(TestServer(create_app(container)))
    await other_client.start_server()
    try:
        other = ApiHelper(other_client)
        response, body = await admin_api.post(
            "/api/admin/invites", json={"max_uses": 1}
        )
        code = body["data"]["invite"]["code"]
        await other.login("disabled@example.com", invite=code)
        response, body = await other.get("/api/me")
        assert response.status == 200
        user_id = body["data"]["user"]["id"]
        response, body = await admin_api.patch(
            f"/api/admin/users/{user_id}", json={"status": "disabled"}
        )
        assert response.status == 200
        response, body = await other.get("/api/me")
        assert response.status == 401
        assert body["error"]["code"] == "unauthorized"
    finally:
        await other_client.close()


async def test_cross_tenant_bot_access_404(api: ApiHelper, invite: str):
    await api.login("owner2@example.com", invite=invite)
    _, body = await api.get("/api/templates")
    template_id = body["data"]["items"][0]["id"]
    _, body = await api.post(
        "/api/bots",
        json={"name": "Owner Bot", "template_id": template_id, "platform": "weixin_oc"},
    )
    bot_id = body["data"]["bot"]["id"]
    await api.client.post("/api/auth/logout", headers=api.headers)
    # admin creates an invite for the second user
    _, body = await api.get("/api/version")
    invite2 = api.client._server.app["container"].invites.create(
        created_by="system", max_uses=1
    )["code"]
    await api.login("other2@example.com", invite=invite2)
    response, body = await api.get(f"/api/bots/{bot_id}")
    assert response.status == 404
    response, body = await api.get(f"/api/bots/{bot_id}/qr/poll")
    assert response.status == 404


async def test_console_redirect_and_static(api: ApiHelper):
    response = await api.client.get("/", allow_redirects=False)
    assert response.status == 302
    assert response.headers["Location"] == "/console/"
    # dist/ is built by the frontend; before that a clear 503 is returned.
    response = await api.client.get("/console/")
    assert response.status in {200, 503}
