"""M5 slice: redemption codes (no payments) + admin user detail + quota patch.

Covers the acceptance points:

* batched generation (``SAAS-XXXX-XXXX``, unambiguous alphabet), listing/filtering,
  disabling;
* redeem is atomic: ``redemption_uses`` + ``used_count`` + ``ledger(grant)`` +
  ``wallets.balance`` + audit ``redemption.redeemed`` stay consistent;
* duplicate redeem by the same user → 409 ``already_redeemed``; invalid / expired
  / exhausted / disabled → explicit 400/410 codes; a code is usable by several
  users up to ``max_uses``;
* admin user detail (profile / wallet / quota / bots / 30d usage / recent ledger)
  and the paginated per-user usage endpoint;
* ``PATCH /api/admin/users/{id}`` quota validation (non-negative integers).
"""

from __future__ import annotations

import re

import pytest

from conftest import ApiHelper
from saas.errors import AppError, Conflict
from saas.redemption import RedemptionService

CODE_RE = re.compile(r"^SAAS-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _service(container) -> RedemptionService:
    service = getattr(container, "redemptions", None)
    if service is None:
        service = RedemptionService(
            container.db, audit=container.audit, clock=container.clock
        )
        container.redemptions = service
    return service


def _user(container, email: str = "redeem@example.com") -> dict:
    return container.auth.create_user(email)


def _codes(container, **kwargs) -> list[dict]:
    payload = {"points": 100, "note": "内测", "count": 1, "max_uses": 1}
    payload.update(kwargs)
    return _service(container).generate(actor="admin", **payload)


def _model(container) -> dict:
    return container.models.create(
        {
            "name": "兑换测试模型",
            "provider": "openai",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-test",
            "points_per_1k_input": 0.5,
            "points_per_1k_output": 1.0,
        },
        actor_id="admin",
    )


async def _bot_for_user(container, user_id: str, name: str = "兑换Bot") -> dict:
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user_id,
        name=name,
        template_id=template["id"],
        platform="weixin_oc",
    )
    return bot


async def _ready_bot_for_user(container, user_id: str, name: str = "就绪Bot") -> dict:
    bot = await _bot_for_user(container, user_id, name)
    container.port.simulate_scan_complete(bot["id"])
    await container.qr.start(user_id=user_id, bot_id=bot["id"])
    await container.qr.poll(user_id=user_id, bot_id=bot["id"])
    await container.qr.finalize(user_id=user_id, bot_id=bot["id"])
    return container.bots.get(bot["id"])


# --------------------------------------------------------------------------
# generation / listing / disabling
# --------------------------------------------------------------------------
def test_generate_batch_and_list(container):
    codes = _codes(container, points=250, note="内测批次", count=3, max_uses=2)
    assert len(codes) == 3
    raw_codes = [item["code"] for item in codes]
    assert len(set(raw_codes)) == 3
    for item in codes:
        assert CODE_RE.match(item["code"]), item["code"]
        assert item["points"] == 250
        assert item["credits"] == 250  # console alias
        assert item["note"] == "内测批次"
        assert item["max_uses"] == 2
        assert item["used_count"] == 0
        assert item["remaining"] == 2
        assert item["disabled"] is False
        assert item["status"] == "active"
        assert item["expires_at"] == 0
        assert item["id"]

    page = _service(container).list_codes(page=1, page_size=2)
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["page"] == 1 and page["page_size"] == 2
    assert _service(container).list_codes(status="active")["total"] == 3
    assert _service(container).list_codes(status="used")["total"] == 0
    assert _service(container).list_codes(status="disabled")["total"] == 0

    # The stored code is plaintext + unique by DB constraint.
    rows = container.db.query("SELECT code FROM redemption_codes")
    assert {row["code"] for row in rows} == set(raw_codes)


def test_generate_validation(container):
    service = _service(container)
    with pytest.raises(AppError) as excinfo:
        service.generate(points=0)
    assert excinfo.value.status == 400
    assert excinfo.value.field == "points"

    for kwargs, field in (
        ({"count": 0}, "count"),
        ({"count": 101}, "count"),
        ({"max_uses": 0}, "max_uses"),
        ({"max_uses": 1001}, "max_uses"),
        ({"expires_at": "abc"}, "expires_at"),
        ({"expires_at": -5}, "expires_at"),
    ):
        with pytest.raises(AppError) as excinfo:
            service.generate(points=10, **kwargs)
        assert excinfo.value.status == 400, kwargs
        assert excinfo.value.field == field, kwargs

    with pytest.raises(AppError):
        service.generate(points="abc")
    with pytest.raises(AppError):
        service.generate(points=10, count=101)


def test_disable_and_list_filter(container):
    code = _codes(container)[0]
    service = _service(container)
    disabled = service.disable(code["id"], actor_id="admin")
    assert disabled["disabled"] is True
    assert disabled["status"] == "disabled"
    assert service.list_codes(status="disabled")["total"] == 1
    assert service.list_codes(status="active")["total"] == 0

    # Resolve by code as well (console sends the code string).
    other = _codes(container)[0]
    assert service.disable(other["code"])["disabled"] is True
    with pytest.raises(AppError) as excinfo:
        service.disable("rc_missing")
    assert excinfo.value.status == 404


async def test_admin_redemption_routes(admin_api: ApiHelper, container):
    response, body = await admin_api.post(
        "/api/admin/redemption-codes",
        json={"points": 80, "note": "API 批次", "count": 2, "max_uses": 3},
    )
    assert response.status == 201, body
    codes = body["data"]["codes"]
    assert body["data"]["count"] == 2
    assert len(codes) == 2 and all(CODE_RE.match(item["code"]) for item in codes)

    response, body = await admin_api.get("/api/admin/redemption-codes?page=1")
    assert response.status == 200, body
    assert body["data"]["total"] == 2
    assert body["data"]["items"][0]["points"] == 80

    code_id = codes[0]["id"]
    response, body = await admin_api.patch(
        f"/api/admin/redemption-codes/{code_id}", json={"disabled": True}
    )
    assert response.status == 200, body
    assert body["data"]["disabled"] is True
    assert body["data"]["code"]["status"] == "disabled"

    # Console-compatible aliases: POST …/{code}/disable and DELETE …/{code}.
    response, body = await admin_api.post(
        f"/api/admin/redemption-codes/{codes[1]['code']}/disable"
    )
    assert response.status == 200, body
    assert body["data"]["disabled"] is True
    response, body = await admin_api.delete(
        f"/api/admin/redemption-codes/{codes[1]['id']}"
    )
    assert response.status == 200, body
    assert body["data"]["deleted"] is True


async def test_admin_redemption_create_accepts_console_aliases(
    admin_api: ApiHelper, container
):
    # web/src/views/admin/RedemptionCodesView.vue sends credits/quantity.
    response, body = await admin_api.post(
        "/api/admin/redemption-codes",
        json={"credits": 90, "quantity": 2, "max_uses": 1, "note": "console"},
    )
    assert response.status == 201, body
    codes = body["data"]["codes"]
    assert len(codes) == 2
    assert codes[0]["points"] == 90 and codes[0]["credits"] == 90


async def test_redemption_routes_require_admin(user_api: ApiHelper):
    response, _ = await user_api.get("/api/admin/redemption-codes")
    assert response.status == 403
    response, _ = await user_api.post(
        "/api/admin/redemption-codes", json={"points": 1}
    )
    assert response.status == 403
    response, _ = await user_api.patch(
        "/api/admin/redemption-codes/rc_x", json={"disabled": True}
    )
    assert response.status == 403


# --------------------------------------------------------------------------
# redeem: success + ledger consistency
# --------------------------------------------------------------------------
def test_redeem_grants_points_and_ledger(container):
    user = _user(container, "grant@example.com")
    code = _codes(container, points=250)[0]
    result = _service(container).redeem(user["id"], code["code"].lower())
    assert result["points"] == 250
    assert result["credits"] == 250
    assert result["balance"] == 250
    assert result["code"] == code["code"]

    assert container.billing.balance(user["id"]) == 250
    assert container.billing.recompute_balance(user["id"]) == 250
    ledger = container.db.query(
        "SELECT * FROM ledger WHERE user_id = ? ORDER BY id DESC", (user["id"],)
    )
    assert len(ledger) == 1
    entry = ledger[0]
    assert entry["type"] == "grant"
    assert entry["delta"] == 250
    assert entry["ref"] == f"redeem:{code['code']}"
    assert entry["idem_key"] == f"redeem:{code['id']}:{user['id']}"

    row = container.db.query_one(
        "SELECT * FROM redemption_codes WHERE id = ?", (code["id"],)
    )
    assert row["used_count"] == 1
    uses = container.db.query(
        "SELECT * FROM redemption_uses WHERE code_id = ?", (code["id"],)
    )
    assert len(uses) == 1 and uses[0]["user_id"] == user["id"]

    audit = container.audit.list(action="redemption.redeemed")
    assert audit["total"] == 1
    assert audit["items"][0]["detail"]["points"] == 250
    assert audit["items"][0]["actor_id"] == user["id"]
    assert audit["items"][0]["actor_role"] == "user"

    # Updated state is visible through the admin listing.
    listed = _service(container).list_codes()["items"]
    target = next(item for item in listed if item["id"] == code["id"])
    assert target["used_count"] == 1
    assert target["status"] == "used"


def test_redeem_duplicate_same_user_conflict(container):
    user = _user(container, "dupe@example.com")
    code = _codes(container, max_uses=2)[0]
    service = _service(container)
    service.redeem(user["id"], code["code"])
    with pytest.raises(Conflict) as excinfo:
        service.redeem(user["id"], code["code"])
    assert excinfo.value.status == 409
    assert excinfo.value.code == "already_redeemed"
    assert container.billing.balance(user["id"]) == 100
    assert container.billing.recompute_balance(user["id"]) == 100
    assert (
        len(container.db.query("SELECT * FROM ledger WHERE user_id = ?", (user["id"],)))
        == 1
    )
    assert (
        container.db.scalar(
            "SELECT used_count FROM redemption_codes WHERE id = ?", (code["id"],)
        )
        == 1
    )


def test_redeem_multiple_users_until_exhausted(container):
    users = [_user(container, f"multi{i}@example.com") for i in range(3)]
    code = _codes(container, max_uses=2, points=40)[0]
    service = _service(container)

    assert service.redeem(users[0]["id"], code["code"])["balance"] == 40
    assert service.redeem(users[1]["id"], code["code"])["balance"] == 40
    with pytest.raises(AppError) as excinfo:
        service.redeem(users[2]["id"], code["code"])
    assert excinfo.value.status == 410
    assert excinfo.value.code == "exhausted"
    assert container.billing.balance(users[2]["id"]) == 0
    assert (
        container.db.scalar(
            "SELECT used_count FROM redemption_codes WHERE id = ?", (code["id"],)
        )
        == 2
    )


def test_redeem_invalid_expired_disabled(container):
    user = _user(container, "badcodes@example.com")
    service = _service(container)

    with pytest.raises(AppError) as excinfo:
        service.redeem(user["id"], "  ")
    assert excinfo.value.status == 400
    assert excinfo.value.code == "validation_error"

    with pytest.raises(AppError) as excinfo:
        service.redeem(user["id"], "SAAS-NOPE-NOPE")
    assert excinfo.value.status == 400
    assert excinfo.value.code == "invalid"

    expired = _codes(container, expires_at=container.clock.now() - 1)[0]
    with pytest.raises(AppError) as excinfo:
        service.redeem(user["id"], expired["code"])
    assert excinfo.value.status == 410
    assert excinfo.value.code == "expired"

    disabled = _codes(container)[0]
    service.disable(disabled["id"])
    with pytest.raises(AppError) as excinfo:
        service.redeem(user["id"], disabled["code"])
    assert excinfo.value.status == 400
    assert excinfo.value.code == "disabled"

    assert container.billing.balance(user["id"]) == 0
    assert container.billing.recompute_balance(user["id"]) == 0
    assert (
        container.db.scalar("SELECT COUNT(*) AS c FROM ledger", (), 0) == 0
    )


async def test_user_redeem_http_flow(user_api: ApiHelper, container):
    code = _codes(container, points=150)[0]

    response, body = await user_api.post("/api/me/redeem", json={"code": code["code"]})
    assert response.status == 200, body
    data = body["data"]
    assert data["points"] == 150 and data["credits"] == 150
    assert data["balance"] == 150
    assert data["code"] == code["code"]

    _, wallet = await user_api.get("/api/wallet")
    assert wallet["data"]["balance"] == 150

    response, body = await user_api.post("/api/me/redeem", json={"code": code["code"]})
    assert response.status == 409, body
    assert body["error"]["code"] == "already_redeemed"

    response, body = await user_api.post(
        "/api/me/redeem", json={"code": "SAAS-BAD1-CODE"}
    )
    assert response.status == 400
    assert body["error"]["code"] == "invalid"


# --------------------------------------------------------------------------
# admin user detail + usage
# --------------------------------------------------------------------------
async def test_admin_user_detail_shape(admin_api: ApiHelper, container):
    user = _user(container, "detail@example.com")
    container.auth.update_quota(
        user["id"], {"max_bots": 4, "max_memories": 50, "monthly_tokens": 123456}
    )
    code = _codes(container, points=100)[0]
    _service(container).redeem(user["id"], code["code"])
    model = _model(container)
    ready = await _ready_bot_for_user(container, user["id"], "详情Bot")
    pending = await _bot_for_user(container, user["id"], "待扫码Bot")
    container.metering.record_usage(
        user["id"], ready["id"], model["id"], 1500, 500, ref="chat:detail"
    )

    response, body = await admin_api.get(f"/api/admin/users/{user['id']}")
    assert response.status == 200, body
    data = body["data"]
    detail = data["user"]
    assert detail["id"] == user["id"]
    assert detail["email"] == "detail@example.com"
    assert detail["display_name"] == "detail"
    assert detail["role"] == "user"
    assert detail["status"] == "active"
    assert detail["created_at"] == container.clock.now()
    assert detail["encryption"]["enabled"] is True
    assert detail["balance"] == 98  # 100 granted - 2 consumed
    assert detail["wallet"]["balance"] == 98
    assert data["wallet"]["balance"] == 98  # top-level alias
    assert detail["bot_count"] == 2
    assert detail["quota"]["max_bots"] == 4
    assert detail["quota"]["max_memories"] == 50
    assert detail["quota"]["monthly_tokens"] == 123456
    assert detail["quota"]["used_tokens"] == 2000
    assert detail["quota"]["used_memories"] == 0

    bots = {bot["id"]: bot for bot in detail["bots"]}
    assert set(bots) == {ready["id"], pending["id"]}
    assert bots[ready["id"]]["enabled"] is True
    assert bots[ready["id"]]["status"] == "ready"
    assert bots[pending["id"]]["enabled"] is False
    for bot in bots.values():
        assert {"id", "name", "platform", "status", "enabled", "created_at"} <= set(bot)

    usage = detail["usage"]
    assert usage["summary30d"]["tokens"] == 2000
    assert usage["summary30d"]["points"] == 2
    assert usage["summary30d"]["requests"] == 1
    assert usage["by_bot"][0]["bot_id"] == ready["id"]
    assert usage["by_bot"][0]["bot_name"] == "详情Bot"
    assert usage["by_bot"][0]["points"] == 2
    assert usage["by_bot"][0]["tokens"] == 2000
    assert usage["by_bot"][0]["requests"] == 1

    ledger = detail["recent_ledger"]
    assert len(ledger) == 2  # grant + consume, newest first
    assert ledger[0]["type"] == "consume" and ledger[0]["delta"] == -2
    assert ledger[1]["type"] == "grant" and ledger[1]["delta"] == 100

    response, body = await admin_api.get("/api/admin/users/u_missing")
    assert response.status == 404


async def test_admin_user_usage_endpoint(admin_api: ApiHelper, container):
    user = _user(container, "detailusage@example.com")
    model = _model(container)
    bot = await _bot_for_user(container, user["id"], "用量Bot")
    container.metering.record_usage(user["id"], bot["id"], model["id"], 1000, 0)
    container.metering.record_usage(user["id"], bot["id"], model["id"], 2000, 0)

    response, body = await admin_api.get(
        f"/api/admin/users/{user['id']}/usage?page=1&page_size=1"
    )
    assert response.status == 200, body
    data = body["data"]
    assert data["total"] == 2
    assert data["page"] == 1 and data["page_size"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["bot_id"] == bot["id"]
    assert item["bot_name"] == "用量Bot"
    assert item["tokens"] == 2000
    assert item["requests"] == 1
    assert data["summary"]["points"] == 2
    assert data["summary"]["tokens"] == 3000
    assert data["summary"]["requests"] == 2

    response, body = await admin_api.get(f"/api/admin/users/{user['id']}/usage?page=2&page_size=1")
    assert response.status == 200
    assert body["data"]["items"][0]["tokens"] == 1000

    response, body = await admin_api.get("/api/admin/users/u_missing/usage")
    assert response.status == 404


async def test_admin_user_detail_requires_admin(user_api: ApiHelper, container):
    user = _user(container, "detailperm@example.com")
    response, _ = await user_api.get(f"/api/admin/users/{user['id']}")
    assert response.status == 403
    response, _ = await user_api.get(f"/api/admin/users/{user['id']}/usage")
    assert response.status == 403


# --------------------------------------------------------------------------
# quota patch validation + effect
# --------------------------------------------------------------------------
async def test_quota_patch_updates_and_validates(admin_api: ApiHelper, container):
    user = _user(container, "quota@example.com")
    response, body = await admin_api.patch(
        f"/api/admin/users/{user['id']}",
        json={
            "quota": {
                "max_bots": 7,
                "max_memories": 123,
                "monthly_tokens": 987654,
            }
        },
    )
    assert response.status == 200, body
    quota = body["data"]["user"]["quota"]
    assert quota["max_bots"] == 7
    assert quota["max_memories"] == 123
    assert quota["monthly_tokens"] == 987654

    # Partial update keeps the other limits.
    response, body = await admin_api.patch(
        f"/api/admin/users/{user['id']}", json={"quota": {"max_bots": 2}}
    )
    assert response.status == 200, body
    quota = body["data"]["user"]["quota"]
    assert quota["max_bots"] == 2
    assert quota["max_memories"] == 123
    assert quota["monthly_tokens"] == 987654

    for payload, field in (
        ({"max_bots": -1}, "max_bots"),
        ({"max_memories": -2}, "max_memories"),
        ({"monthly_tokens": -3}, "monthly_tokens"),
        ({"max_bots": "abc"}, "max_bots"),
        ({"monthly_tokens": 1.5}, "monthly_tokens"),
        ({"max_memories": True}, "max_memories"),
    ):
        response, body = await admin_api.patch(
            f"/api/admin/users/{user['id']}", json={"quota": payload}
        )
        assert response.status == 400, (payload, body)
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["field"] == field

    audit = container.audit.list(action="user.quota_changed")
    assert audit["total"] == 2

    response, body = await admin_api.patch(
        "/api/admin/users/u_missing", json={"quota": {"max_bots": 1}}
    )
    assert response.status == 404
