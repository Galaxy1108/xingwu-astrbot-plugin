"""FR-C/FR-D acceptance: templates, bot creation rollback, lifecycle, isolation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from conftest import ApiHelper
from saas.errors import AppError
from saas.fake_astrbot import FakeAstrBot


def _template(container) -> dict:
    return container.templates.list(enabled_only=True)[0]


async def _create_user(container, invite: str, email: str = "u@example.com") -> dict:
    code = container.auth.request_otp(email, invite=invite)["dev_code"]
    return container.auth.verify_otp(email, code, invite=invite)["user"]


async def test_create_bot_registers_everything(container, invite, clock):
    user = await _create_user(container, invite)
    template = _template(container)
    bot = await container.bots.create(
        user_id=user["id"],
        name="小明",
        template_id=template["id"],
        platform="weixin_oc",
    )
    assert bot["status"] == "pending_qr"
    assert bot["persona_name"].startswith("saas_")
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot["id"],))
    assert row["snapshot"]
    assert container.port.state.personas.get(row["persona_name"])
    assert container.port.state.configs.get(row["conf_id"])
    assert container.port.state.routes.get(f"{bot['id']}::") == row["conf_id"]
    assert container.port.state.platforms.get(bot["id"])["enable"] is False
    memory_file = container.settings.memory_dir / f"{bot['id']}.db"
    assert memory_file.exists()
    # The memory library is SQLCipher, not plain SQLite.
    assert not memory_file.read_bytes()[:16].startswith(b"SQLite format 3")
    with pytest.raises(sqlite3.DatabaseError):
        plain = sqlite3.connect(memory_file)
        plain.execute("SELECT * FROM memories").fetchall()


async def test_template_snapshot_is_frozen(container, invite):
    user = await _create_user(container, invite)
    template = _template(container)
    bot = await container.bots.create(
        user_id=user["id"], name="A", template_id=template["id"], platform="weixin_oc"
    )
    before = container.db.query_one(
        "SELECT snapshot FROM bots WHERE id = ?", (bot["id"],)
    )["snapshot"]
    container.templates.update(template["id"], {"persona_prompt": "改了"})
    after = container.db.query_one(
        "SELECT snapshot FROM bots WHERE id = ?", (bot["id"],)
    )["snapshot"]
    assert before == after


async def test_disabled_template_rejected(container, invite):
    user = await _create_user(container, invite)
    template = _template(container)
    container.templates.disable(template["id"])
    with pytest.raises(AppError) as info:
        await container.bots.create(
            user_id=user["id"],
            name="A",
            template_id=template["id"],
            platform="weixin_oc",
        )
    assert info.value.code == "template_disabled"
    assert info.value.status == 409


async def test_quota_exceeded(container, invite):
    user = await _create_user(container, invite)
    template = _template(container)
    container.db.execute(
        "UPDATE quotas SET max_bots = 1 WHERE user_id = ?", (user["id"],)
    )
    await container.bots.create(
        user_id=user["id"], name="A", template_id=template["id"], platform="weixin_oc"
    )
    with pytest.raises(AppError) as info:
        await container.bots.create(
            user_id=user["id"],
            name="B",
            template_id=template["id"],
            platform="weixin_oc",
        )
    assert info.value.code == "quota_exceeded"


@pytest.mark.parametrize(
    "fail_step",
    [
        "create_config",
        "bind_route",
        "create_platform",
        "create_persona",
    ],
)
async def test_failed_creation_rolls_back_everything(container, invite, fail_step):
    user = await _create_user(container, invite)
    template = _template(container)
    port = container.port
    assert isinstance(port, FakeAstrBot)
    port.fail_on = {fail_step}
    with pytest.raises(AppError):
        await container.bots.create(
            user_id=user["id"],
            name="失败Bot",
            template_id=template["id"],
            platform="weixin_oc",
        )
    port.fail_on = set()
    assert container.db.scalar("SELECT COUNT(*) AS c FROM bots", (), 0) == 0
    assert port.state.personas == {}
    assert port.state.configs == {}
    assert port.state.routes == {}
    assert port.state.platforms == {}
    assert list(container.settings.memory_dir.glob("*.db*")) == []


async def test_bot_isolation_and_cross_tenant_404(container, invite):
    user_a = await _create_user(container, invite, "a@example.com")
    inv_b = container.invites.create(created_by="system")["code"]
    user_b = await _create_user(container, inv_b, "b@example.com")
    template = _template(container)
    bot = await container.bots.create(
        user_id=user_a["id"], name="A 的 bot", template_id=template["id"], platform="weixin_oc"
    )
    with pytest.raises(AppError) as info:
        container.bots.get_for_user(user_b["id"], bot["id"])
    assert info.value.status == 404


async def test_rename_keeps_technical_fields(container, invite):
    user = await _create_user(container, invite)
    template = _template(container)
    bot = await container.bots.create(
        user_id=user["id"], name="旧名", template_id=template["id"], platform="weixin_oc"
    )
    before = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot["id"],))
    renamed = await container.bots.rename(
        user_id=user["id"], bot_id=bot["id"], name="新名"
    )
    after = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot["id"],))
    assert renamed["name"] == "新名"
    for field in ("persona_name", "conf_id", "memory_db", "template_id"):
        assert before[field] == after[field]


async def test_delete_requires_exact_name(container, invite):
    user = await _create_user(container, invite)
    template = _template(container)
    bot = await container.bots.create(
        user_id=user["id"], name="要删的", template_id=template["id"], platform="weixin_oc"
    )
    with pytest.raises(AppError) as info:
        await container.bots.delete(
            user_id=user["id"], bot_id=bot["id"], confirm_name="错的"
        )
    assert info.value.field == "confirm_name"
    await container.bots.delete(
        user_id=user["id"], bot_id=bot["id"], confirm_name="要删的"
    )
    assert container.db.scalar("SELECT COUNT(*) AS c FROM bots", (), 0) == 0
    assert container.port.state.personas == {}
    assert container.port.state.configs == {}
    assert container.port.state.platforms == {}
    assert container.port.state.routes == {}
    assert list(container.settings.memory_dir.glob("*.db*")) == []


async def test_api_create_list_delete(user_api: ApiHelper, container):
    _, body = await user_api.get("/api/templates")
    template_id = body["data"]["items"][0]["id"]
    response, body = await user_api.post(
        "/api/bots",
        json={"name": "API Bot", "template_id": template_id, "platform": "qq_official"},
    )
    assert response.status == 201, body
    bot = body["data"]["bot"]
    assert bot["status"] == "pending_qr"
    response, body = await user_api.get("/api/bots")
    assert len(body["data"]["items"]) == 1
    response, body = await user_api.delete(
        f"/api/bots/{bot['id']}", json={"confirm_name": "API Bot"}
    )
    assert response.status == 200
    assert body["data"]["deleted"] is True
    response, body = await user_api.get(f"/api/bots/{bot['id']}")
    assert response.status == 404


async def test_healthz_and_version(api: ApiHelper):
    response, body = await api.get("/healthz")
    assert response.status == 200 and body["data"]["ok"] is True
    response, body = await api.get("/api/version")
    assert response.status == 200 and body["data"]["version"]
