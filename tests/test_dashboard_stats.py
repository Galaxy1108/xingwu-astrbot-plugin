"""User dashboard aggregates (points instead of tokens)."""

from __future__ import annotations

from conftest import ApiHelper


async def test_dashboard_stats_aggregates(user_api: ApiHelper, container):
    user = container.auth.get_user_by_email("user@example.com")
    model = container.models.create(
        {"name": "Stats Model", "model": "stats-model", "points_per_1k_input": 1,
         "points_per_1k_output": 2},
        actor_id="admin",
    )
    container.metering.record_usage(
        user_id=user["id"], bot_id="", model_id=model["id"],
        tokens_in=1000, tokens_out=500, ref="stats", idem_key="stats-1",
    )
    response, body = await user_api.get("/api/me/stats?days=30")
    assert response.status == 200
    data = body["data"]
    assert data["total_points"] > 0
    assert data["total_tokens"] == 1500
    assert data["total_requests"] == 1
    assert data["by_model"][0]["model_name"] == "Stats Model"
    assert data["by_model"][0]["points"] > 0
    assert len(data["points"]) == 30
    assert data["by_platform"]
