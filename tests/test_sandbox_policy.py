"""Admin Agent sandbox policy."""

from __future__ import annotations

import asyncio

from conftest import ADMIN_EMAIL, ApiHelper


async def _wait_job(admin_api: ApiHelper, job_id: str, attempts: int = 200) -> dict:
    """Poll the sandbox job endpoint until it leaves ``running``."""
    for _ in range(attempts):
        response, body = await admin_api.get(f"/api/admin/sandbox/jobs/{job_id}")
        assert response.status == 200
        if body["data"]["status"] != "running":
            return body["data"]
        await asyncio.sleep(0.01)
    raise AssertionError(f"sandbox job {job_id} did not finish")


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
    assert response.status == 202
    assert body["data"]["total"] == 0
    job = await _wait_job(admin_api, body["data"]["job_id"])
    assert job["status"] == "done"
    assert job["done"] == 0 and job["failed"] == 0 and job["errors"] == []
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
    assert response.status == 202
    response, body = await admin_api.put(
        "/api/admin/sandbox",
        json={"policy": {"enabled": True, "runtime": "none", "limits": {"cpu_seconds": 0}}},
    )
    assert response.status == 202
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


async def test_user_can_choose_runtime_when_allowed(user_api: ApiHelper, container):
    user = container.auth.get_user_by_email("user@example.com")
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"], name="Runtime Bot", template_id=template["id"],
        platform="weixin_oc",
    )
    container.settings_store.set(
        "sandbox.policy",
        {
            "enabled": True,
            "allow_user_config": True,
            "runtime": "local",
            "require_admin": True,
            "booter": "docker",
            "limits": {"cpu_seconds": 60, "memory_mb": 512, "file_size_mb": 32,
                       "open_files": 128, "processes": 64},
        },
    )
    response, body = await user_api.patch(
        f"/api/bots/{bot['id']}",
        json={"settings": {"agent_enabled": True, "sandbox_runtime": "sandbox"}},
    )
    assert response.status == 200
    assert body["data"]["bot"]["sandbox"]["runtime"] == "sandbox"


async def test_sandbox_job_completes_and_isolates_bot_failures(
    user_api: ApiHelper, container, monkeypatch
):
    user = container.auth.get_user_by_email("user@example.com")
    template = container.templates.list(enabled_only=True)[0]
    bot_ids = []
    for name in ("Job Bot A", "Job Bot B", "Job Bot C"):
        bot = await container.bots.create(
            user_id=user["id"], name=name, template_id=template["id"],
            platform="weixin_oc",
        )
        bot_ids.append(bot["id"])
    conf_of = {
        bot_id: container.db.query_one("SELECT conf_id FROM bots WHERE id = ?", (bot_id,))["conf_id"]
        for bot_id in bot_ids
    }
    failing_bot, healthy = bot_ids[1], [bot_ids[0], bot_ids[2]]

    original_update = container.port.update_config

    async def flaky_update(conf_id, patch):
        if conf_id == conf_of[failing_bot]:
            # The message carries a fake credential to prove it is never surfaced.
            raise RuntimeError("upstream rejected key sk-SECRET-123")
        return await original_update(conf_id, patch)

    monkeypatch.setattr(container.port, "update_config", flaky_update)

    admin_api = user_api
    await admin_api.login(ADMIN_EMAIL)  # single shared client: one admin login only
    policy = {
        "enabled": True,
        "runtime": "none",
        "require_admin": True,
        "booter": "docker",
        "limits": {"cpu_seconds": 60, "memory_mb": 512, "file_size_mb": 32,
                   "open_files": 128, "processes": 64},
    }
    response, body = await admin_api.put("/api/admin/sandbox", json={"policy": policy})
    assert response.status == 202
    assert body["data"]["total"] == 3
    assert body["data"]["limits_installed"] in (True, False)
    job_id = body["data"]["job_id"]

    job = await _wait_job(admin_api, job_id)
    assert job["status"] == "done"
    assert job["total"] == 3
    assert job["done"] == 2
    assert job["failed"] == 1
    assert [item["bot_id"] for item in job["errors"]] == [failing_bot]
    assert "sk-SECRET" not in str(job["errors"])
    for bot_id in healthy:
        patched = container.port.state.configs[conf_of[bot_id]]
        assert patched["provider_settings.sandbox.booter"] == "docker"

    response, body = await admin_api.get("/api/admin/sandbox/jobs/no-such-job")
    assert response.status == 404
