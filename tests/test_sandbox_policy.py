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
