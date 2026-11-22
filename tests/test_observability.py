"""Health endpoint and error/log observability."""

from __future__ import annotations

from conftest import ApiHelper


async def test_health_and_error_logs(admin_api: ApiHelper, container):
    response, body = await admin_api.get("/api/health")
    assert response.status == 200
    assert body["data"] == {"status": "ok", "db": "ok"}

    response, body = await admin_api.get("/api/admin/health/detail")
    assert response.status == 200
    detail = body["data"]
    assert detail["status"] == "ok"
    assert detail["db"] == "ok"
    for key in (
        "backend",
        "backend_connected",
        "version",
        "uptime_seconds",
        "recent_errors_1h",
    ):
        assert key in detail

    container.error_logs.record(
        level="error",
        message="upstream api_key=secret-123 failed",
        code="upstream_error",
        path="/api/models",
        status=502,
    )
    response, body = await admin_api.get("/api/admin/error-logs")
    assert response.status == 200
    items = body["data"]["items"]
    assert items and items[0]["code"] == "upstream_error"
    assert "secret-123" not in items[0]["message"]

    response, body = await admin_api.get("/api/admin/logs?lines=5")
    assert response.status == 200
    assert "items" in body["data"]


async def test_public_health_hides_details_from_anonymous(api, container):
    response, body = await api.get("/api/health")
    assert response.status == 200
    assert set(body["data"]) == {"status", "db"}

    response, body = await api.get("/api/admin/health/detail")
    assert response.status in (401, 403)
