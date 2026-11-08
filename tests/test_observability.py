"""Health endpoint and error/log observability."""

from __future__ import annotations

from conftest import ApiHelper


async def test_health_and_error_logs(admin_api: ApiHelper, container):
    response, body = await admin_api.get("/api/health")
    assert response.status == 200
    assert body["data"]["status"] == "ok"
    assert body["data"]["db"] == "ok"

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
