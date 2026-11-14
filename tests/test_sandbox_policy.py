"""Admin Agent sandbox policy."""

from __future__ import annotations

from conftest import ApiHelper


async def test_sandbox_get_and_update(admin_api: ApiHelper, container):
    response, body = await admin_api.get("/api/admin/sandbox")
    assert response.status == 200
    assert body["data"]["policy"]["runtime"] == "none"
    assert body["data"]["platform"]["os"]

    policy = {
        "enabled": True,
        "runtime": "none",
        "require_admin": True,
        "booter": "docker",
        "limits": {
            "cpu_seconds": 60,
            "memory_mb": 512,
            "file_size_mb": 32,
            "open_files": 128,
            "processes": 64,
        },
    }
    response, body = await admin_api.put("/api/admin/sandbox", json={"policy": policy})
    assert response.status == 200
    saved = body["data"]["policy"]
    assert saved["limits"]["cpu_seconds"] == 60
    assert saved["limits"]["memory_mb"] == 512
    assert container.settings_store.get("sandbox.policy")["limits"]["processes"] == 64


async def test_sandbox_validation(admin_api: ApiHelper):
    response, body = await admin_api.put(
        "/api/admin/sandbox",
        json={"policy": {"enabled": True, "runtime": "wat"}},
    )
    # unknown runtime falls back to none rather than failing
    assert response.status == 200
    response, body = await admin_api.put(
        "/api/admin/sandbox",
        json={"policy": {"enabled": True, "runtime": "none", "limits": {"cpu_seconds": 0}}},
    )
    assert response.status == 200
    assert body["data"]["policy"]["limits"]["cpu_seconds"] == 300


async def test_sandbox_requires_admin(user_api: ApiHelper):
    response, body = await user_api.get("/api/admin/sandbox")
    assert response.status == 403


async def test_user_sandbox_display_and_toggle(user_api: ApiHelper, container):
    user = container.auth.get_user_by_email("user@example.com")
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"], name="Sandbox Bot", template_id=template["id"],
        platform="weixin_oc",
    )
    container.settings_store.set(
        "sandbox.policy",
        {
            "enabled": True,
            "allow_user_config": True,
            "runtime": "none",
            "require_admin": True,
            "booter": "docker",
            "limits": {"cpu_seconds": 60, "memory_mb": 512, "file_size_mb": 32,
                       "open_files": 128, "processes": 64},
        },
    )
    response, body = await user_api.get(f"/api/bots/{bot['id']}")
    sandbox = body["data"]["bot"]["sandbox"]
    assert sandbox["policy_enabled"] is True
    assert sandbox["user_configurable"] is True
    assert sandbox["limits"]["cpu_seconds"] == 60

    response, body = await user_api.patch(
        f"/api/bots/{bot['id']}", json={"settings": {"agent_enabled": False}}
    )
    assert response.status == 200
    assert body["data"]["bot"]["sandbox"]["enabled"] is False

    container.settings_store.set(
        "sandbox.policy",
        {"enabled": True, "allow_user_config": False, "runtime": "none"},
    )
    response, body = await user_api.patch(
        f"/api/bots/{bot['id']}", json={"settings": {"agent_enabled": True}}
    )
    assert response.status == 403
    assert body["error"]["code"] == "sandbox_locked"
