"""M3 slice: manual credit orders + append-only ledger (idempotent)."""

from __future__ import annotations

from conftest import ApiHelper


def _user(container, email: str = "bill@example.com") -> dict:
    return container.auth.create_user(email)


def test_order_confirm_creates_single_grant(container):
    user = _user(container)
    created = container.billing.create_order(
        admin_id="admin", user_id=user["id"], credits=500, amount_cny=5.0
    )
    order = created["order"]
    result = container.billing.confirm_order(order_id=order["id"], admin_id="admin")
    assert result["order"]["status"] == "paid"
    assert container.billing.balance(user["id"]) == 500
    assert container.billing.recompute_balance(user["id"]) == 500
    ledger = container.billing.ledger(user["id"])
    assert ledger["total"] == 1
    assert ledger["items"][0]["delta"] == 500
    # Confirming again must not double-credit.
    again = container.billing.confirm_order(order_id=order["id"], admin_id="admin")
    assert again["already_paid"] is True
    assert container.billing.balance(user["id"]) == 500
    assert container.billing.recompute_balance(user["id"]) == 500


def test_order_external_ref_is_idempotent(container):
    user = _user(container)
    first = container.billing.create_order(
        admin_id="admin", user_id=user["id"], credits=100, external_ref="TX-1"
    )
    second = container.billing.create_order(
        admin_id="admin", user_id=user["id"], credits=100, external_ref="TX-1"
    )
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert second["order"]["id"] == first["order"]["id"]


def test_manual_adjust_and_idempotency(container):
    user = _user(container)
    first = container.billing.adjust(
        admin_id="admin", user_id=user["id"], delta=1000, reason="补偿", idem_key="K1"
    )
    assert first["idempotent"] is False
    assert first["balance"] == 1000
    duplicate = container.billing.adjust(
        admin_id="admin", user_id=user["id"], delta=1000, reason="补偿", idem_key="K1"
    )
    assert duplicate["idempotent"] is True
    assert container.billing.balance(user["id"]) == 1000
    deduction = container.billing.adjust(
        admin_id="admin", user_id=user["id"], delta=-200, reason="退款", idem_key="K2"
    )
    assert deduction["balance"] == 800
    assert container.billing.recompute_balance(user["id"]) == 800


def test_reconcile_repairs_cached_balance(container):
    user = _user(container)
    container.billing.adjust(admin_id="admin", user_id=user["id"], delta=300)
    container.db.execute(
        "UPDATE wallets SET balance = 999 WHERE user_id = ?", (user["id"],)
    )
    assert container.billing.balance(user["id"]) == 999
    result = container.billing.reconcile(user["id"])
    assert result["balance"] == 300
    assert container.billing.balance(user["id"]) == 300


async def test_wallet_api_reads_ledger(user_api: ApiHelper, container):
    _, body = await user_api.get("/api/me")
    user_id = body["data"]["user"]["id"]
    container.billing.adjust(admin_id="admin", user_id=user_id, delta=250)
    response, body = await user_api.get("/api/wallet")
    assert response.status == 200
    assert body["data"]["balance"] == 250
    assert body["data"]["ledger_total"] == 250
    response, body = await user_api.get("/api/wallet/ledger")
    assert response.status == 200
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["delta"] == 250


async def test_admin_order_api(admin_api: ApiHelper, container):
    user = _user(container, "ordertarget@example.com")
    response, body = await admin_api.post(
        "/api/admin/orders",
        json={"user_id": user["id"], "credits": 1200, "amount_cny": 12, "note": "手动"},
    )
    assert response.status == 201, body
    order_id = body["data"]["order"]["id"]
    response, body = await admin_api.post(f"/api/admin/orders/{order_id}/confirm")
    assert response.status == 200
    assert body["data"]["order"]["status"] == "paid"
    response, body = await admin_api.get("/api/admin/orders")
    assert response.status == 200
    assert body["data"]["total"] >= 1
    assert body["data"]["items"][0]["user_email"] == "ordertarget@example.com"
    response, body = await admin_api.post(
        f"/api/admin/ledger", json={"user_id": user["id"], "delta": -200, "reason": "扣减"}
    )
    assert response.status == 200
    assert body["data"]["balance"] == 1000
    # non-admin cannot touch billing
    response, body = await admin_api.post(
        "/api/admin/ledger", json={"user_id": user["id"], "delta": 1}
    )
    assert response.status == 200


async def test_billing_forbidden_for_users(user_api: ApiHelper, container):
    user = _user(container, "billinguser@example.com")
    response, body = await user_api.post(
        "/api/admin/orders", json={"user_id": user["id"], "credits": 1}
    )
    assert response.status == 403
    response, body = await user_api.post(
        "/api/admin/ledger", json={"user_id": user["id"], "delta": 1}
    )
    assert response.status == 403
