"""AstrBot token usage → metering bridge."""

from __future__ import annotations

from conftest import ApiHelper


async def _setup(container, invite, *, with_profile=True):
    code = container.auth.request_otp("bridge@example.com", invite=invite)["dev_code"]
    user = container.auth.verify_otp("bridge@example.com", code, invite=invite)["user"]
    if with_profile:
        container.models.create(
            {
                "name": "Bridge Model",
                "provider": "openai",
                "model": "bridge-model",
                "points_per_1k_input": 1,
                "points_per_1k_output": 2,
            },
            actor_id="admin",
        )
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"],
        name="Bridge Bot",
        template_id=template["id"],
        platform="weixin_oc",
    )
    return user, bot


async def test_bridge_records_real_tokens(container, invite):
    user, bot = await _setup(container, invite, with_profile=True)
    result = container.usage_bridge.record(
        bot["id"], 1000, 500, model_name="bridge-model", ref="llm:resp-1", idem_key="llm:resp-1"
    )
    assert result["recorded"] is True
    usage = container.db.query_one(
        "SELECT * FROM usage_records WHERE bot_id = ?", (bot["id"],)
    )
    assert usage is not None
    assert usage["tokens_in"] == 1000 and usage["tokens_out"] == 500
    assert usage["points"] == 2  # 1 + 1
    ledger = container.db.query_one(
        "SELECT * FROM ledger WHERE ref = ?", (f"usage:{usage['id']}",)
    )
    assert ledger is not None and ledger["delta"] == -2
    wallet = container.db.query_one(
        "SELECT balance FROM wallets WHERE user_id = ?", (user["id"],)
    )
    assert wallet["balance"] == -2
    # idempotent: same response id must not bill twice
    again = container.usage_bridge.record(
        bot["id"], 1000, 500, model_name="bridge-model", ref="llm:resp-1", idem_key="llm:resp-1"
    )
    assert again.get("idempotent") is True
    assert container.db.scalar("SELECT COUNT(*) FROM usage_records", (), 0) == 1


async def test_bridge_skips_without_pricing_profile(container, invite):
    user, bot = await _setup(container, invite, with_profile=False)
    result = container.usage_bridge.record(bot["id"], 100, 100, model_name="missing")
    assert result["recorded"] is False
    assert result["reason"] == "no_pricing_profile"
    assert container.db.scalar("SELECT COUNT(*) FROM usage_records", (), 0) == 0
