"""M6 slice: account bans, appeals, admin bot disable and restore-on-unban.

Covers the contract:

* banning snapshots only *enabled* bots, disables them (row + adapter) and
  revokes sessions; unban restores exactly those bots (manual stops stay off);
* banned users can still OTP-login and reach only ``/api/me``,
  ``/api/me/appeals``, ``/api/appeals``, logout and version — everything else is
  403 ``account_banned`` with the reason;
* appeals: create/list/approve/reject, duplicate pending 409, one pending per
  target, audit rows;
* admin bot disable → owner cannot re-enable (403 ``admin_disabled``) → appeal →
  approve → bot is enabled again.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from conftest import ApiHelper


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
@asynccontextmanager
async def _secondary_client(container) -> AsyncIterator[ApiHelper]:
    """A second browser client (admin_api/user_api share one cookie jar)."""
    from aiohttp.test_utils import TestClient, TestServer

    from saas.web.app import create_app

    client = TestClient(TestServer(create_app(container)))
    await client.start_server()
    try:
        yield ApiHelper(client)
    finally:
        await client.close()


def _otp_user(container, email: str, invite: str | None = None) -> tuple[dict, str]:
    code = container.auth.request_otp(email, invite=invite)["dev_code"]
    result = container.auth.verify_otp(email, code, invite=invite)
    return result["user"], result["session"]["token"]


async def _ready_bot(container, user_id: str, name: str = "封禁Bot") -> dict:
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user_id,
        name=name,
        template_id=template["id"],
        platform="weixin_oc",
    )
    container.port.simulate_scan_complete(bot["id"])
    await container.qr.start(user_id=user_id, bot_id=bot["id"])
    await container.qr.poll(user_id=user_id, bot_id=bot["id"])
    return await container.qr.finalize(user_id=user_id, bot_id=bot["id"])


def _bot_row(container, bot_id: str) -> dict:
    return container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))


def _user_row(container, user_id: str) -> dict:
    return container.db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def _platform_enabled(container, bot_id: str) -> bool:
    return bool(container.port.state.platforms[bot_id]["enable"])


async def _ban(admin_api: ApiHelper, user_id: str, reason: str = "违规测试"):
    return await admin_api.patch(
        f"/api/admin/users/{user_id}", json={"status": "disabled", "reason": reason}
    )


# --------------------------------------------------------------------------
# banning
# --------------------------------------------------------------------------
async def test_ban_snapshots_only_enabled_bots(admin_api: ApiHelper, container, invite):
    user, token = _otp_user(container, "ban1@example.com", invite)
    ready = await _ready_bot(container, user["id"], "开启Bot")
    manual = await _ready_bot(container, user["id"], "手动停用Bot")
    await container.bots.set_enabled(
        user_id=user["id"], bot_id=manual["id"], enabled=False
    )

    response, body = await _ban(admin_api, user["id"], "垃圾内容")
    assert response.status == 200, body
    assert body["data"]["user"]["status"] == "disabled"
    assert body["data"]["user"]["status_reason"] == "垃圾内容"
    assert body["data"]["user"]["status_changed_at"] == container.clock.now()

    row = _user_row(container, user["id"])
    assert row["status"] == "disabled"
    assert row["status_reason"] == "垃圾内容"
    assert row["disabled_at"] == container.clock.now()
    assert container.db.query_one(
        "SELECT banned_restore_bots FROM users WHERE id = ?", (user["id"],)
    )["banned_restore_bots"] == f'["{ready["id"]}"]'

    ready_row = _bot_row(container, ready["id"])
    assert ready_row["status"] == "disabled"
    assert ready_row["admin_disabled"] == 1
    assert ready_row["disabled_reason"] == "垃圾内容"
    assert ready_row["disabled_at"] == container.clock.now()
    assert _platform_enabled(container, ready["id"]) is False

    manual_row = _bot_row(container, manual["id"])
    assert manual_row["status"] == "disabled"
    assert manual_row["admin_disabled"] == 0  # user had already stopped it

    # Sessions are revoked immediately.
    assert container.sessions.resolve(token) is None
    audit = container.audit.list(action="user.banned")
    assert audit["total"] == 1
    assert audit["items"][0]["detail"]["reason"] == "垃圾内容"
    assert audit["items"][0]["detail"]["restored_bots"] == [ready["id"]]


async def test_ban_is_idempotent_and_keeps_snapshot(admin_api: ApiHelper, container):
    user = container.auth.create_user("ban2@example.com")
    bot = await _ready_bot(container, user["id"])
    await _ban(admin_api, user["id"], "第一次")
    first = _user_row(container, user["id"])["banned_restore_bots"]
    assert bot["id"] in first

    response, body = await _ban(admin_api, user["id"], "第二次")
    assert response.status == 200, body
    assert _user_row(container, user["id"])["banned_restore_bots"] == first
    assert _user_row(container, user["id"])["status_reason"] == "第二次"


# --------------------------------------------------------------------------
# banned login + restricted API + appeal
# --------------------------------------------------------------------------
async def test_banned_user_login_and_restricted_api(admin_api: ApiHelper, container):
    user = container.auth.create_user("banned3@example.com")
    await _ready_bot(container, user["id"])
    await _ban(admin_api, user["id"], "违反社区规范")

    async with _secondary_client(container) as other:
        await other.login("banned3@example.com")  # OTP login still succeeds
        response, body = await other.get("/api/me")
        assert response.status == 200, body
        assert body["data"]["user"]["status"] == "disabled"
        assert body["data"]["user"]["status_reason"] == "违反社区规范"
        assert body["data"]["user"]["pending_appeal"] is None

        response, body = await other.get("/api/bots")
        assert response.status == 403, body
        assert body["error"]["code"] == "account_banned"
        assert body["error"]["reason"] == "违反社区规范"

        response, body = await other.get("/api/admin/users")
        assert response.status == 403
        assert body["error"]["code"] == "account_banned"

        response, body = await other.get("/api/me/appeals")
        assert response.status == 200, body
        assert body["data"]["items"] == []

        response, body = await other.post(
            "/api/appeals",
            json={"target_type": "user", "reason": "我保证不再违规，请解封"},
        )
        assert response.status == 201, body
        appeal = body["data"]["appeal"]
        assert appeal["status"] == "pending"
        assert appeal["target_type"] == "user"
        assert appeal["target_id"] == ""

        _, me = await other.get("/api/me")
        pending = me["data"]["user"]["pending_appeal"]
        assert pending is not None and pending["id"] == appeal["id"]

        response, body = await other.post(
            "/api/appeals",
            json={"target_type": "user", "reason": "再来一次"},
        )
        assert response.status == 409, body
        assert body["error"]["code"] == "appeal_pending"


async def test_ban_appeal_approve_restores_user_and_bots(admin_api: ApiHelper, container):
    user = container.auth.create_user("appeal4@example.com")
    bot = await _ready_bot(container, user["id"])
    await _ban(admin_api, user["id"], "误封了")

    async with _secondary_client(container) as other:
        await other.login("appeal4@example.com")
        _, body = await other.post(
            "/api/appeals", json={"target_type": "user", "reason": "我是被误封的"}
        )
        appeal_id = body["data"]["appeal"]["id"]

        response, body = await admin_api.get("/api/admin/appeals?status=pending")
        assert response.status == 200, body
        item = body["data"]["items"][0]
        assert item["id"] == appeal_id
        assert item["user_email"] == "appeal4@example.com"
        assert item["target_type"] == "user"
        assert item["status"] == "pending"

        response, body = await admin_api.post(
            f"/api/admin/appeals/{appeal_id}/approve", json={"note": "核实后解封"}
        )
        assert response.status == 200, body
        approved = body["data"]["appeal"]
        assert approved["status"] == "approved"
        assert approved["admin_note"] == "核实后解封"
        assert approved["admin_id"]
        assert approved["resolved_at"] == container.clock.now()

        # The still-valid banned session is no longer gated.
        response, body = await other.get("/api/bots")
        assert response.status == 200, body
        _, me = await other.get("/api/me")
        assert me["data"]["user"]["status"] == "active"
        assert me["data"]["user"]["status_reason"] == ""
        assert me["data"]["user"]["pending_appeal"] is None

    row = _user_row(container, user["id"])
    assert row["status"] == "active"
    assert row["banned_restore_bots"] == "[]"
    bot_row = _bot_row(container, bot["id"])
    assert bot_row["status"] == "ready"
    assert bot_row["admin_disabled"] == 0
    assert _platform_enabled(container, bot["id"]) is True

    assert container.audit.list(action="user.unbanned")["total"] == 1
    assert container.audit.list(action="appeal.approved")["total"] == 1


async def test_unban_direct_restores_only_enabled_bots(admin_api: ApiHelper, container):
    user = container.auth.create_user("unban5@example.com")
    enabled_bot = await _ready_bot(container, user["id"], "开启Bot")
    manual_bot = await _ready_bot(container, user["id"], "手动停用Bot")
    await container.bots.set_enabled(
        user_id=user["id"], bot_id=manual_bot["id"], enabled=False
    )
    await _ban(admin_api, user["id"], "临时封禁")

    response, body = await admin_api.patch(
        f"/api/admin/users/{user['id']}",
        json={"status": "active", "reason": "申诉通过"},
    )
    assert response.status == 200, body
    assert body["data"]["user"]["status"] == "active"
    assert body["data"]["user"]["status_reason"] == ""

    assert _bot_row(container, enabled_bot["id"])["status"] == "ready"
    assert _platform_enabled(container, enabled_bot["id"]) is True
    manual_row = _bot_row(container, manual_bot["id"])
    assert manual_row["status"] == "disabled"
    assert manual_row["admin_disabled"] == 0
    assert _platform_enabled(container, manual_bot["id"]) is False

    assert _user_row(container, user["id"])["banned_restore_bots"] == "[]"
    audit = container.audit.list(action="user.unbanned")
    assert audit["total"] == 1
    assert audit["items"][0]["detail"]["restored_bots"] == [enabled_bot["id"]]
    assert audit["items"][0]["detail"]["reason"] == "申诉通过"


# --------------------------------------------------------------------------
# admin bot disable + bot appeal
# --------------------------------------------------------------------------
async def test_admin_bot_disable_blocks_owner_and_restores_on_approve(
    admin_api: ApiHelper, container
):
    user = container.auth.create_user("bot6@example.com")
    bot = await _ready_bot(container, user["id"], "违规Bot")

    response, body = await admin_api.patch(
        f"/api/admin/bots/{bot['id']}",
        json={"disabled": True, "reason": "内容违规"},
    )
    assert response.status == 200, body
    item = body["data"]["bot"]
    assert item["admin_disabled"] is True
    assert item["disabled_reason"] == "内容违规"
    assert item["status"] == "disabled"
    assert _platform_enabled(container, bot["id"]) is False

    _, listing = await admin_api.get("/api/admin/bots")
    listed = next(b for b in listing["data"]["items"] if b["id"] == bot["id"])
    assert listed["admin_disabled"] is True
    assert listed["admin_disabled_reason"] == "内容违规"

    async with _secondary_client(container) as other:
        await other.login("bot6@example.com")
        response, body = await other.patch(
            f"/api/bots/{bot['id']}", json={"enabled": True}
        )
        assert response.status == 403, body
        assert body["error"]["code"] == "admin_disabled"
        assert "内容违规" in body["error"]["message"]

        response, body = await other.post(
            "/api/appeals",
            json={
                "target_type": "bot",
                "target_id": bot["id"],
                "reason": "这个 Bot 是我的，请恢复",
            },
        )
        assert response.status == 201, body
        appeal_id = body["data"]["appeal"]["id"]

        response, body = await other.post(
            "/api/appeals",
            json={
                "target_type": "bot",
                "target_id": bot["id"],
                "reason": "重复申诉",
            },
        )
        assert response.status == 409, body
        assert body["error"]["code"] == "appeal_pending"

        _, mine = await other.get("/api/me/appeals")
        assert [item["id"] for item in mine["data"]["items"]] == [appeal_id]

        response, body = await admin_api.post(
            f"/api/admin/appeals/{appeal_id}/approve", json={"note": "已核实"}
        )
        assert response.status == 200, body
        assert body["data"]["appeal"]["status"] == "approved"

    row = _bot_row(container, bot["id"])
    assert row["admin_disabled"] == 0
    assert row["status"] == "ready"
    assert _platform_enabled(container, bot["id"]) is True
    assert container.audit.list(action="bot.admin_disabled")["total"] == 1
    assert container.audit.list(action="bot.admin_enabled")["total"] == 1


async def test_bot_appeal_target_validation(admin_api: ApiHelper, container):
    owner = container.auth.create_user("owner7@example.com")
    container.auth.create_user("intruder7@example.com")
    bot = await _ready_bot(container, owner["id"], "私有Bot")
    await admin_api.patch(
        f"/api/admin/bots/{bot['id']}",
        json={"disabled": True, "reason": "违规"},
    )

    async with _secondary_client(container) as other:
        await other.login("intruder7@example.com")
        response, body = await other.post(
            "/api/appeals",
            json={"target_type": "bot", "target_id": bot["id"], "reason": "不是我的"},
        )
        assert response.status == 404
        # Active account cannot file a user-ban appeal.
        response, body = await other.post(
            "/api/appeals",
            json={"target_type": "user", "reason": "我没被封"},
        )
        assert response.status == 400, body
        # Missing target id.
        response, body = await other.post(
            "/api/appeals", json={"target_type": "bot", "reason": "x"}
        )
        assert response.status == 400

    async with _secondary_client(container) as owner_client:
        await owner_client.login("owner7@example.com")
        # Appeal only applies to admin-disabled bots.
        other_bot = await _ready_bot(container, owner["id"], "正常Bot")
        response, body = await owner_client.post(
            "/api/appeals",
            json={"target_type": "bot", "target_id": other_bot["id"], "reason": "x"},
        )
        assert response.status == 400, body


# --------------------------------------------------------------------------
# reject / resolved / permissions
# --------------------------------------------------------------------------
async def test_reject_appeal_keeps_ban_and_allows_new_appeal(
    admin_api: ApiHelper, container
):
    user = container.auth.create_user("reject8@example.com")
    await _ready_bot(container, user["id"])
    await _ban(admin_api, user["id"], "严重违规")

    async with _secondary_client(container) as other:
        await other.login("reject8@example.com")
        _, body = await other.post(
            "/api/appeals", json={"target_type": "user", "reason": "第一次申诉"}
        )
        appeal_id = body["data"]["appeal"]["id"]

        response, body = await admin_api.post(
            f"/api/admin/appeals/{appeal_id}/reject", json={"note": "理由不充分"}
        )
        assert response.status == 200, body
        appeal = body["data"]["appeal"]
        assert appeal["status"] == "rejected"
        assert appeal["admin_note"] == "理由不充分"
        assert appeal["resolved_at"] == container.clock.now()

        # Ban is still in place.
        _, me = await other.get("/api/me")
        assert me["data"]["user"]["status"] == "disabled"
        assert _bot_row(container, container.db.scalar(
            "SELECT id FROM bots WHERE user_id = ?", (user["id"],)
        ))["status"] == "disabled"

        # A rejected appeal frees the pending slot.
        response, body = await other.post(
            "/api/appeals", json={"target_type": "user", "reason": "补充材料"}
        )
        assert response.status == 201, body

    assert container.audit.list(action="appeal.rejected")["total"] == 1


async def test_resolved_appeal_conflict_and_admin_permissions(
    admin_api: ApiHelper, container
):
    user = container.auth.create_user("resolve9@example.com")
    await _ban(admin_api, user["id"], "封禁")
    appeal = container.appeals.create(user["id"], "user", reason="申诉一下")

    response, body = await admin_api.post(
        f"/api/admin/appeals/{appeal['id']}/approve", json={}
    )
    assert response.status == 200, body
    # Already resolved → 409 for both actions.
    for action in ("approve", "reject"):
        response, body = await admin_api.post(
            f"/api/admin/appeals/{appeal['id']}/{action}", json={"note": "again"}
        )
        assert response.status == 409, body
        assert body["error"]["code"] == "appeal_resolved"
    response, body = await admin_api.post("/api/admin/appeals/ap_missing/approve", json={})
    assert response.status == 404

    async with _secondary_client(container) as other:
        await other.login("resolve9@example.com")
        response, body = await other.get("/api/admin/appeals")
        assert response.status == 403
        assert body["error"]["code"] == "forbidden"
        response, body = await other.post(
            f"/api/admin/appeals/{appeal['id']}/approve", json={}
        )
        assert response.status == 403


async def test_admin_user_list_and_detail_show_ban_and_appeal(
    admin_api: ApiHelper, container
):
    user = container.auth.create_user("list10@example.com")
    bot = await _ready_bot(container, user["id"], "列表Bot")
    await _ban(admin_api, user["id"], "列表封禁")
    container.appeals.create(user["id"], "user", reason="列表申诉")

    response, body = await admin_api.get("/api/admin/users?q=list10")
    assert response.status == 200, body
    item = next(i for i in body["data"]["items"] if i["id"] == user["id"])
    assert item["status_reason"] == "列表封禁"
    assert item["pending_appeal"] is not None
    assert item["pending_appeal"]["target_type"] == "user"
    assert item["appeal_count"] == 1

    response, body = await admin_api.get(f"/api/admin/users/{user['id']}")
    assert response.status == 200, body
    detail = body["data"]["user"]
    assert detail["status_reason"] == "列表封禁"
    assert detail["pending_appeal"] is not None
    assert detail["appeal_count"] == 1
    detail_bot = next(b for b in detail["bots"] if b["id"] == bot["id"])
    assert detail_bot["admin_disabled"] is True
    assert detail_bot["disabled_reason"] == "列表封禁"

    _, bots = await admin_api.get("/api/admin/bots")
    listed = next(b for b in bots["data"]["items"] if b["id"] == bot["id"])
    assert listed["admin_disabled"] is True
    assert listed["disabled_reason"] == "列表封禁"


async def test_ban_validation_and_not_found(admin_api: ApiHelper, container):
    response, body = await admin_api.patch(
        "/api/admin/users/u_missing", json={"status": "disabled"}
    )
    assert response.status == 404
    response, body = await admin_api.patch(
        "/api/admin/users/u_missing", json={"status": "deleted"}
    )
    assert response.status == 400
    assert body["error"]["field"] == "status"

    response, body = await admin_api.patch(
        "/api/admin/bots/b_missing", json={"disabled": True}
    )
    assert response.status == 404
    response, body = await admin_api.patch(
        "/api/admin/bots/b_missing", json={}
    )
    assert response.status == 400
    assert body["error"]["field"] == "disabled"
    response, body = await admin_api.patch(
        "/api/admin/bots/b_missing", json={"disabled": "yes"}
    )
    assert response.status == 400

    user = container.auth.create_user("perm11@example.com")
    async with _secondary_client(container) as other:
        await other.login("perm11@example.com")
        response, body = await other.patch(
            f"/api/admin/users/{user['id']}", json={"status": "disabled"}
        )
        assert response.status == 403
