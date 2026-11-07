"""M4 slice: model catalog (sealed keys), pricing and usage metering.

Covers the acceptance points of the M4 API contract (docs/API.md §5):

* API keys are sealed in the DB (no plaintext at rest) and only masked over HTTP.
* ``points = ceil(tokens_in/1000*in_price + tokens_out/1000*out_price)``.
* usage + ledger + wallet + quota writes are atomic and idempotent.
* insufficient balance (when ``billing.enforce_balance``) → 409, nothing written.
* permissions and template ``model_profile_id`` snapshotting.
"""

from __future__ import annotations

import json

import pytest

from conftest import ApiHelper
from saas.metering import MeteringService
from saas.model_catalog import ModelCatalogService

SECRET = "sk-test-secret-123"


# --------------------------------------------------------------------------
# wiring helpers: container.py/app.py registration is owned by the Lead.  The
# overrides below attach the M4 services/routes when they are not wired yet, so
# this module is self-contained (and still works once the Lead wires them).
# --------------------------------------------------------------------------
@pytest.fixture
def container(container):
    if not hasattr(container, "models"):
        container.models = ModelCatalogService(
            container.db,
            key_manager=container.key_manager,
            audit=container.audit,
            clock=container.clock,
        )
    if not hasattr(container, "metering"):
        container.metering = MeteringService(
            container.db,
            audit=container.audit,
            clock=container.clock,
            settings_store=container.settings_store,
            catalog=container.models,
        )
    return container


def _register_models_routes(app) -> None:
    from saas.web import routes_models

    registered = {
        getattr(getattr(route, "resource", None), "canonical", None)
        for route in app.router.routes()
    }
    if "/api/models" not in registered:
        app.add_routes(routes_models.routes)


@pytest.fixture
async def api(container):
    from aiohttp.test_utils import TestClient, TestServer

    from saas.web.app import create_app

    app = create_app(container)
    _register_models_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield ApiHelper(client)
    finally:
        await client.close()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _user(container, email: str = "usage@example.com") -> dict:
    return container.auth.create_user(email)


def _fund(container, user_id: str, amount: int = 100) -> None:
    container.billing.adjust(admin_id="admin", user_id=user_id, delta=amount)


def _model(container, **overrides) -> dict:
    payload = {
        "name": "GPT-4o mini",
        "provider": "openai",
        "base_url": "https://api.example.com/v1",
        "model": "gpt-4o-mini",
        "api_key": SECRET,
        "points_per_1k_input": 0.5,
        "points_per_1k_output": 1.0,
    }
    payload.update(overrides)
    return container.models.create(payload, actor_id="admin")


def _ledger(container, user_id: str) -> list[dict]:
    return container.db.query(
        "SELECT * FROM ledger WHERE user_id = ? ORDER BY id", (user_id,)
    )


# --------------------------------------------------------------------------
# model catalog
# --------------------------------------------------------------------------
async def test_create_model_seals_key_and_masks_http_response(
    admin_api: ApiHelper, container
):
    response, body = await admin_api.post(
        "/api/admin/models",
        json={
            "name": "Claude",
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "model": "claude-3-5-sonnet",
            "api_key": SECRET,
            "points_per_1k_input": 3,
            "points_per_1k_output": 15,
            "note": "生产",
        },
    )
    assert response.status == 201, body
    model = body["data"]["model"]
    assert model["has_api_key"] is True
    assert model["api_key"] != SECRET
    assert model["api_key"] and "•" in model["api_key"]
    assert model["enabled"] is True
    assert model["base_url"] == "https://api.anthropic.com/v1"
    assert "api_key_cipher" not in json.dumps(model)

    row = container.db.query_one(
        "SELECT * FROM model_profiles WHERE id = ?", (model["id"],)
    )
    assert row["api_key_cipher"] is not None
    # No plaintext anywhere in the stored row nor in the SQLite file/WAL.
    assert SECRET not in json.dumps({k: str(v) for k, v in row.items()})
    db_bytes = container.settings.db_path.read_bytes()
    wal = container.settings.db_path.with_name(
        container.settings.db_path.name + "-wal"
    )
    if wal.exists():
        db_bytes += wal.read_bytes()
    assert SECRET.encode() not in db_bytes

    # The service can still unwrap it for upstream calls.
    assert container.models.secret(model["id"]) == SECRET
    # AAD is bound to the profile id: re-using the blob under another id fails.
    other = _model(container, name="Other", model="other")
    container.db.execute(
        "UPDATE model_profiles SET api_key_cipher = ? WHERE id = ?",
        (row["api_key_cipher"], other["id"]),
    )
    with pytest.raises(Exception):
        container.models.secret(other["id"])

    raw = await response.text()
    assert SECRET not in raw


async def test_model_validation_errors(admin_api: ApiHelper):
    cases = [
        ({"name": "x", "model": ""}, "model"),
        ({"name": "", "model": "m"}, "name"),
        (
            {"name": "x", "model": "m", "points_per_1k_input": -1},
            "points_per_1k_input",
        ),
        (
            {"name": "x", "model": "m", "points_per_1k_input": "abc"},
            "points_per_1k_input",
        ),
        (
            {"name": "x", "model": "m", "base_url": "ftp://example.com"},
            "base_url",
        ),
    ]
    for payload, field in cases:
        response, body = await admin_api.post("/api/admin/models", json=payload)
        assert response.status == 400, (payload, body)
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["field"] == field

    response, body = await admin_api.patch(
        "/api/admin/models/m_missing", json={"enabled": False}
    )
    assert response.status == 404


async def test_model_update_disable_and_delete(admin_api: ApiHelper, container):
    model = _model(container)
    response, body = await admin_api.patch(
        f"/api/admin/models/{model['id']}",
        json={"enabled": False, "points_per_1k_input": 2.5},
    )
    assert response.status == 200, body
    assert body["data"]["model"]["enabled"] is False
    assert body["data"]["model"]["points_per_1k_input"] == 2.5
    # Disabled profiles disappear from the user-facing catalog.
    assert model["id"] not in {
        item["id"] for item in container.models.public_list()
    }

    # Clearing the key must flip has_api_key and keep the row valid.
    response, body = await admin_api.patch(
        f"/api/admin/models/{model['id']}", json={"api_key": ""}
    )
    assert response.status == 200, body
    assert body["data"]["model"]["has_api_key"] is False

    response, body = await admin_api.delete(f"/api/admin/models/{model['id']}")
    assert response.status == 200, body
    assert body["data"]["deleted"] is True
    # Soft delete keeps the profile (and its price history) but disables it.
    assert container.models.get(model["id"])["enabled"] is False
    assert model["id"] not in {
        item["id"] for item in container.models.public_list()
    }
    # Deleting again is idempotent; re-enabling is allowed.
    response, body = await admin_api.delete(f"/api/admin/models/{model['id']}")
    assert response.status == 200 and body["data"]["deleted"] is True
    response, body = await admin_api.patch(
        f"/api/admin/models/{model['id']}", json={"enabled": True}
    )
    assert response.status == 200
    assert body["data"]["model"]["enabled"] is True

    response, body = await admin_api.delete("/api/admin/models/m_missing")
    assert response.status == 404


# --------------------------------------------------------------------------
# pricing + metering
# --------------------------------------------------------------------------
def test_pricing_formula_and_ledger_consistency(container):
    user = _user(container, "pricing@example.com")
    _fund(container, user["id"], 100)
    model = _model(
        container, points_per_1k_input=0.5, points_per_1k_output=1.0
    )

    result = container.metering.record_usage(
        user["id"], "b_1", model["id"], 1500, 500, ref="chat:1"
    )
    # ceil(1.5*0.5 + 0.5*1.0) == ceil(1.25) == 2
    assert result["points"] == 2
    assert result["idempotent"] is False
    usage = result["usage"]
    assert usage["tokens_in"] == 1500
    assert usage["tokens_out"] == 500
    assert usage["model_name"] == "GPT-4o mini"
    assert usage["user_id"] == user["id"]

    assert container.billing.balance(user["id"]) == 98
    assert container.billing.recompute_balance(user["id"]) == 98
    entries = _ledger(container, user["id"])
    consumption = [entry for entry in entries if entry["type"] == "consume"]
    assert len(consumption) == 1
    assert consumption[0]["delta"] == -2
    assert consumption[0]["ref"] == f"usage:{usage['id']}"

    quota = container.db.query_one(
        "SELECT used_tokens FROM quotas WHERE user_id = ?", (user["id"],)
    )
    assert quota["used_tokens"] == 2000

    audit = container.audit.list(action="usage.recorded")
    assert audit["total"] == 1
    assert audit["items"][0]["detail"]["points"] == 2

    summary = container.metering.usage_summary(user["id"], days=30)
    assert summary["tokens_in"] == 1500
    assert summary["tokens_out"] == 500
    assert summary["points"] == 2
    assert summary["records"] == 1


def test_usage_idempotent_by_idem_key(container):
    user = _user(container, "idem@example.com")
    _fund(container, user["id"], 100)
    model = _model(container)

    first = container.metering.record_usage(
        user["id"], "", model["id"], 1000, 0, idem_key="req-1"
    )
    assert first["idempotent"] is False
    assert first["points"] == 1

    second = container.metering.record_usage(
        user["id"], "", model["id"], 1000, 0, idem_key="req-1"
    )
    assert second["idempotent"] is True
    assert second["usage"]["id"] == first["usage"]["id"]

    assert container.db.scalar(
        "SELECT COUNT(*) AS c FROM usage_records WHERE user_id = ?", (user["id"],)
    ) == 1
    assert container.billing.balance(user["id"]) == 99
    assert container.billing.recompute_balance(user["id"]) == 99
    assert container.db.scalar(
        "SELECT used_tokens FROM quotas WHERE user_id = ?", (user["id"],)
    ) == 1000
    assert len(
        [entry for entry in _ledger(container, user["id"]) if entry["type"] == "consume"]
    ) == 1


def test_usage_rejects_unknown_model_and_bad_tokens(container):
    user = _user(container, "bad@example.com")
    model = _model(container)
    with pytest.raises(Exception) as excinfo:
        container.metering.record_usage(user["id"], "", "m_missing", 1, 1)
    assert getattr(excinfo.value, "status", None) == 404

    from saas.errors import ValidationError

    with pytest.raises(ValidationError):
        container.metering.record_usage(user["id"], "", model["id"], -1, 0)
    with pytest.raises(ValidationError):
        container.metering.record_usage(user["id"], "", model["id"], "x", 0)


def test_insufficient_balance_blocks_every_write(container):
    user = _user(container, "poor@example.com")
    _fund(container, user["id"], 1)
    model = _model(container, points_per_1k_input=10, points_per_1k_output=10)
    container.settings_store.set("billing.enforce_balance", True)

    from saas.errors import Conflict

    with pytest.raises(Conflict) as excinfo:
        container.metering.record_usage(
            user["id"], "", model["id"], 1000, 0, idem_key="poor-1"
        )
    error = excinfo.value
    assert error.status == 409
    assert error.code == "insufficient_balance"

    assert container.db.scalar(
        "SELECT COUNT(*) AS c FROM usage_records", ()
    ) == 0
    assert container.billing.balance(user["id"]) == 1
    assert container.billing.recompute_balance(user["id"]) == 1
    assert container.db.scalar(
        "SELECT used_tokens FROM quotas WHERE user_id = ?", (user["id"],)
    ) == 0
    assert [entry for entry in _ledger(container, user["id"]) if entry["type"] == "consume"] == []


async def test_insufficient_balance_over_http(admin_api: ApiHelper, container):
    user = _user(container, "poor2@example.com")
    _fund(container, user["id"], 1)
    model = _model(container, points_per_1k_input=10, points_per_1k_output=10)
    container.settings_store.set("billing.enforce_balance", True)

    response, body = await admin_api.post(
        "/api/admin/usage",
        json={
            "user_id": user["id"],
            "model_id": model["id"],
            "tokens_in": 5000,
            "tokens_out": 5000,
        },
    )
    assert response.status == 409, body
    assert body["error"]["code"] == "insufficient_balance"


# --------------------------------------------------------------------------
# HTTP: usage endpoints
# --------------------------------------------------------------------------
async def test_admin_usage_endpoints(admin_api: ApiHelper, container):
    user = _user(container, "adminusage@example.com")
    _fund(container, user["id"], 100)
    model = _model(container)

    response, body = await admin_api.post(
        "/api/admin/usage",
        json={
            "user_id": user["id"],
            "bot_id": "b_1",
            "model_id": model["id"],
            "tokens_in": 1000,
            "tokens_out": 1000,
            "ref": "chat:42",
            "idem_key": "admin-1",
        },
    )
    assert response.status == 201, body
    assert body["data"]["points"] == 2
    assert body["data"]["idempotent"] is False
    assert body["data"]["balance"] == 98

    # Same idem_key over HTTP → 200 + idempotent, no double charge.
    response, body = await admin_api.post(
        "/api/admin/usage",
        json={
            "user_id": user["id"],
            "model_id": model["id"],
            "tokens_in": 1000,
            "tokens_out": 1000,
            "idem_key": "admin-1",
        },
    )
    assert response.status == 200, body
    assert body["data"]["idempotent"] is True
    assert container.billing.balance(user["id"]) == 98

    response, body = await admin_api.get(
        f"/api/admin/usage?user_id={user['id']}"
    )
    assert response.status == 200, body
    data = body["data"]
    assert data["total"] == 1
    assert data["items"][0]["ref"] == "chat:42"
    assert data["summary"]["points"] == 2
    assert set(data) >= {"items", "total", "page", "page_size", "summary"}


async def test_user_usage_endpoint(user_api: ApiHelper, container):
    _, me = await user_api.get("/api/me")
    user_id = me["data"]["user"]["id"]
    _fund(container, user_id, 100)
    model = _model(container)
    container.metering.record_usage(user_id, "", model["id"], 1000, 0)

    response, body = await user_api.get("/api/me/usage?page=1")
    assert response.status == 200, body
    data = body["data"]
    assert data["page"] == 1
    assert data["total"] == 1
    assert data["items"][0]["tokens_in"] == 1000
    assert data["summary"]["days"] == 30
    assert data["summary"]["tokens"] == 1000


# --------------------------------------------------------------------------
# HTTP: user catalog + permissions
# --------------------------------------------------------------------------
async def test_user_catalog_hides_keys_and_base_url(user_api: ApiHelper, container):
    enabled = _model(container, name="Enabled")
    _model(container, name="Disabled", enabled=False)

    response, body = await user_api.get("/api/models")
    assert response.status == 200, body
    items = body["data"]["items"]
    assert [item["id"] for item in items] == [enabled["id"]]
    item = items[0]
    assert "api_key" not in item and "api_key_cipher" not in item
    assert "base_url" not in item
    raw = await response.text()
    assert SECRET not in raw
    assert "api.example.com" not in raw
    assert item["points_per_1k_input"] == 0.5


async def test_model_permissions(user_api: ApiHelper, container):
    response, body = await user_api.get("/api/admin/models")
    assert response.status == 403
    response, body = await user_api.post(
        "/api/admin/models", json={"name": "x", "model": "m"}
    )
    assert response.status == 403
    response, body = await user_api.get("/api/admin/usage")
    assert response.status == 403
    response, body = await user_api.post(
        "/api/admin/usage", json={"user_id": "u_x", "model_id": "m_x"}
    )
    assert response.status == 403


async def test_models_require_login(api: ApiHelper):
    response, _ = await api.get("/api/models")
    assert response.status == 401
    response, _ = await api.get("/api/me/usage")
    assert response.status == 401


# --------------------------------------------------------------------------
# templates
# --------------------------------------------------------------------------
async def test_template_model_profile_is_snapshotted(admin_api: ApiHelper, container):
    model = _model(container)
    response, body = await admin_api.post(
        "/api/admin/templates",
        json={"name": "带模型", "model_profile_id": model["id"]},
    )
    assert response.status == 201, body
    template = body["data"]["template"]
    assert template["model_profile_id"] == model["id"]

    response, body = await admin_api.patch(
        f"/api/admin/templates/{template['id']}",
        json={"model_profile_id": ""},
    )
    assert response.status == 200, body
    assert body["data"]["template"]["model_profile_id"] == ""

    # Snapshot captured at Bot creation keeps the profile id it was created with.
    container.templates.update(template["id"], {"model_profile_id": model["id"]})
    snapshot = container.templates.snapshot(template["id"])
    assert snapshot["model_profile_id"] == model["id"]
    container.templates.update(template["id"], {"model_profile_id": ""})
    assert container.templates.snapshot(template["id"])["model_profile_id"] == ""

    # Invalid model_profile_id type/width is rejected.
    response, body = await admin_api.patch(
        f"/api/admin/templates/{template['id']}",
        json={"model_profile_id": "x" * 65},
    )
    assert response.status == 400
    assert body["error"]["field"] == "model_profile_id"


# --------------------------------------------------------------------------
# connectivity probe
# --------------------------------------------------------------------------
async def test_model_probe_success_and_failure_is_sanitised(
    admin_api: ApiHelper, container
):
    model = _model(container)

    async def ok_probe(base_url, api_key, row):
        assert base_url == "https://api.example.com/v1"
        assert api_key == SECRET
        assert row["model"] == "gpt-4o-mini"
        return 200

    container.models.prober = ok_probe
    response, body = await admin_api.post(f"/api/admin/models/{model['id']}/test")
    assert response.status == 200, body
    assert body["data"]["ok"] is True
    assert body["data"]["status"] == 200

    async def failing_probe(base_url, api_key, row):
        raise RuntimeError(f"connect failed for {base_url} with {api_key}")

    container.models.prober = failing_probe
    response, body = await admin_api.post(f"/api/admin/models/{model['id']}/test")
    assert response.status == 502, body
    assert body["error"]["code"] == "upstream_error"
    raw = await response.text()
    assert SECRET not in raw
    assert "connect failed" not in raw
