"""M1 acceptance mapping (详见 docs/ACCEPTANCE.md §A–F)."""

from __future__ import annotations

import concurrent.futures

import pytest

from conftest import ApiHelper
from saas.errors import AppError


# ---------------------------------------------------------------- A. invites
def test_invite_concurrent_consumption_single_winner(container, invite):
    """并发消耗同一个一次性邀请码：只能有一个成功，其余 410。"""
    def consume():
        try:
            container.invites.consume(invite)
            return "ok"
        except AppError as exc:  # noqa: PERF203
            return exc.code

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: consume(), range(8)))
    assert results.count("ok") == 1
    assert results.count("invite_exhausted") == 7


# ------------------------------------------------------------ B. rollback
async def test_invalid_payload_leaves_no_residue(container, invite):
    code = container.auth.request_otp("bad@example.com", invite=invite)["dev_code"]
    user = container.auth.verify_otp("bad@example.com", code, invite=invite)["user"]
    template = container.templates.list(enabled_only=True)[0]
    with pytest.raises(AppError):
        await container.bots.create(
            user_id=user["id"],
            name="x",
            template_id=template["id"],
            platform="telegram",  # not supported
        )
    assert container.db.scalar("SELECT COUNT(*) AS c FROM bots", (), 0) == 0
    assert container.port.state.personas == {}
    assert list(container.settings.memory_dir.glob("*.db*")) == []


# ------------------------------------------------------- C. QR already covered
# tests/test_qr.py: TTL/refresh/idle/finalize/credentials


# ------------------------------------------------- D. session / permissions
async def test_admin_disable_user_stops_bots(container, invite):
    code = container.auth.request_otp("u9@example.com", invite=invite)["dev_code"]
    user = container.auth.verify_otp("u9@example.com", code, invite=invite)["user"]
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"], name="要停的", template_id=template["id"], platform="weixin_oc"
    )
    container.port.simulate_scan_complete(bot["id"])
    await container.qr.start(user_id=user["id"], bot_id=bot["id"])
    await container.qr.poll(user_id=user["id"], bot_id=bot["id"])
    ready = await container.qr.finalize(user_id=user["id"], bot_id=bot["id"])
    assert ready["status"] == "ready"
    container.auth.set_user_status(user["id"], "disabled", actor_id="admin")
    await container.bots.disable_all_for_user(user["id"])
    row = container.db.query_one("SELECT status FROM bots WHERE id = ?", (bot["id"],))
    assert row["status"] == "disabled"
    assert container.port.state.platforms[bot["id"]]["enable"] is False


async def test_audit_trail_covers_login_and_bot_actions(admin_api: ApiHelper, invite: str):
    await admin_api.client.post("/api/auth/otp/request", json={"email": "a1@example.com"})
    # login as the seeded admin already produced auth.login; create a bot too.
    _, body = await admin_api.get("/api/templates")
    template_id = body["data"]["items"][0]["id"]
    _, body = await admin_api.post(
        "/api/bots",
        json={"name": "审计Bot", "template_id": template_id, "platform": "qq_official"},
    )
    bot_id = body["data"]["bot"]["id"]
    _, body = await admin_api.delete(
        f"/api/bots/{bot_id}", json={"confirm_name": "审计Bot"}
    )
    _, body = await admin_api.get("/api/admin/audit?page_size=100")
    actions = {item["action"] for item in body["data"]["items"]}
    assert {"auth.login", "bot.created", "bot.deleted"} <= actions
    assert any(item["target_id"] == bot_id for item in body["data"]["items"])


async def test_admin_bot_list_includes_owner_email(admin_api: ApiHelper):
    _, body = await admin_api.get("/api/templates")
    template_id = body["data"]["items"][0]["id"]
    _, body = await admin_api.post(
        "/api/bots",
        json={"name": "管理员Bot", "template_id": template_id, "platform": "weixin_oc"},
    )
    _, body = await admin_api.get("/api/admin/bots")
    assert body["data"]["total"] >= 1
    assert all("owner_email" in item for item in body["data"]["items"])


async def test_invite_admin_flow(admin_api: ApiHelper):
    response, body = await admin_api.post(
        "/api/admin/invites", json={"max_uses": 2, "ttl_hours": 4}
    )
    assert response.status == 201
    code = body["data"]["invite"]["code"]
    _, body = await admin_api.get("/api/admin/invites")
    item = next(i for i in body["data"]["items"] if i["code_hint"] == code[:8])
    assert item["status"] == "active"
    response, body = await admin_api.delete(f"/api/admin/invites/{code[:8]}")
    assert response.status == 200 and body["data"]["revoked"] is True


async def test_admin_quota_update_validation(admin_api: ApiHelper):
    _, body = await admin_api.get("/api/admin/users")
    user_id = body["data"]["items"][0]["id"]
    response, body = await admin_api.patch(
        f"/api/admin/users/{user_id}", json={"quota": {"max_bots": "abc"}}
    )
    assert response.status == 400
    assert body["error"]["code"] == "validation_error"


async def test_template_references_astrbot_conf_profile(container, invite, admin_api: ApiHelper):
    # admin endpoint exposes demo AstrBot profiles in the fake adapter
    response, body = await admin_api.get("/api/admin/conf-profiles")
    assert response.status == 200
    ids = {item["id"] for item in body["data"]["items"]}
    assert "default" in ids and "conf_companion" in ids

    response, body = await admin_api.post(
        "/api/admin/templates",
        json={"name": "配置文件模板", "base_conf_id": "conf_companion"},
    )
    assert response.status == 201
    template = body["data"]["template"]
    assert template["base_conf_id"] == "conf_companion"

    # bot creation clones that AstrBot profile
    code = container.auth.request_otp("conftpl@example.com", invite=invite)["dev_code"]
    user = container.auth.verify_otp("conftpl@example.com", code, invite=invite)["user"]
    bot = await container.bots.create(
        user_id=user["id"],
        name="配置模板 Bot",
        template_id=template["id"],
        platform="weixin_oc",
    )
    conf = container.port.state.configs.get(
        container.db.query_one("SELECT conf_id FROM bots WHERE id = ?", (bot["id"],))["conf_id"]
    )
    assert conf["base_conf_id"] == "conf_companion"


async def test_admin_overview_reports_ledger_totals(admin_api: ApiHelper, container):
    user = container.auth.create_user("overviewtarget@example.com")
    container.billing.adjust(admin_id="admin", user_id=user["id"], delta=500)
    container.billing.adjust(admin_id="admin", user_id=user["id"], delta=-120)
    response, body = await admin_api.get("/api/admin/overview")
    assert response.status == 200
    data = body["data"]
    for field in (
        "users",
        "bots",
        "ready_bots",
        "balance_total",
        "granted_points",
        "deducted_points",
        "tokens_used",
        "tokens_metered",
        "balance_scope",
    ):
        assert field in data
    assert data["balance_scope"] == "platform_points_ledger"
    assert data["adjusted_in_points"] >= 500
    assert data["deducted_points"] >= 120


async def test_wallet_usage_series(admin_api: ApiHelper, container):
    response, body = await admin_api.get("/api/wallet/usage?days=7")
    assert response.status == 200
    assert body["data"]["days"] == 7
    assert len(body["data"]["points"]) == 7
    assert body["data"]["scope"] == "platform_points_ledger"
