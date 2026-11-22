"""Password login brute-force protection: unified errors, lockout, reset, expiry."""

from __future__ import annotations

from conftest import ApiHelper
from saas.clock import FrozenClock
from saas.container import Container

PASSWORD = "secret123"
WRONG = "wrong-password"


def _register(container: Container, invite: str, username: str = "carol") -> None:
    container.auth.register_with_password(
        invite=invite, username=username, password=PASSWORD
    )


async def _login(api: ApiHelper, identifier: str, password: str):
    return await api.post(
        "/api/auth/password/login",
        json={"identifier": identifier, "password": password},
    )


async def test_unknown_and_passwordless_accounts_share_one_error(
    api: ApiHelper, container: Container
):
    container.auth.create_user("nopass@example.com")
    cases = [
        ("nobody", PASSWORD),  # unknown username
        ("ghost@example.com", PASSWORD),  # unknown email
        ("nopass@example.com", PASSWORD),  # OTP-only account, no password
    ]
    for identifier, password in cases:
        response, body = await _login(api, identifier, password)
        assert response.status == 401, identifier
        assert body["error"]["code"] == "invalid_credentials", identifier


async def test_repeated_failures_lock_account_with_429(
    api: ApiHelper, container: Container, invite: str
):
    _register(container, invite)
    for _ in range(5):
        response, body = await _login(api, "carol", WRONG)
        assert response.status == 401
        assert body["error"]["code"] == "invalid_credentials"

    # Locked: even the correct password is refused until the window passes.
    response, body = await _login(api, "carol", PASSWORD)
    assert response.status == 429
    assert body["error"]["code"] == "too_many_attempts"
    assert 0 < body["error"]["retry_after"] <= 900
    assert int(response.headers["Retry-After"]) == body["error"]["retry_after"]


async def test_unknown_accounts_are_counted_too(api: ApiHelper):
    for _ in range(5):
        response, _ = await _login(api, "ghost", WRONG)
        assert response.status == 401
    response, body = await _login(api, "ghost", WRONG)
    assert response.status == 429
    assert body["error"]["code"] == "too_many_attempts"


async def test_identifier_is_normalized_for_counting(
    api: ApiHelper, container: Container, invite: str
):
    _register(container, invite)
    for identifier in ("carol", " Carol ", "CAROL", "carol", "cArOl"):
        await _login(api, identifier, WRONG)
    response, body = await _login(api, "carol", PASSWORD)
    assert response.status == 429
    assert body["error"]["code"] == "too_many_attempts"


async def test_successful_login_clears_failure_count(
    api: ApiHelper, container: Container, invite: str
):
    _register(container, invite)
    for _ in range(4):
        await _login(api, "carol", WRONG)
    response, _ = await _login(api, "carol", PASSWORD)
    assert response.status == 200

    # Counter was reset: four more failures still do not lock the account.
    for _ in range(4):
        response, body = await _login(api, "carol", WRONG)
        assert response.status == 401
        assert body["error"]["code"] == "invalid_credentials"
    response, _ = await _login(api, "carol", PASSWORD)
    assert response.status == 200


async def test_lock_expires_after_window(
    api: ApiHelper, container: Container, invite: str, clock: FrozenClock
):
    _register(container, invite)
    for _ in range(5):
        await _login(api, "carol", WRONG)

    clock.tick(100)
    response, body = await _login(api, "carol", PASSWORD)
    assert response.status == 429
    assert 780 <= body["error"]["retry_after"] <= 800

    clock.tick(901)
    response, body = await _login(api, "carol", PASSWORD)
    assert response.status == 200, body


async def test_ip_dimension_limits_across_identifiers(
    api: ApiHelper, container: Container, invite: str
):
    _register(container, invite)
    container.settings.login_ip_max_failures = 3
    for name in ("u1", "u2", "u3"):
        response, body = await _login(api, name, WRONG)
        assert response.status == 401
    # Fourth attempt from the same IP is throttled even for a fresh identifier.
    response, body = await _login(api, "brand-new", WRONG)
    assert response.status == 429
    assert body["error"]["code"] == "too_many_attempts"
