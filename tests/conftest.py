"""Shared fixtures: frozen clock, fake AstrBot port, container and HTTP client."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from saas.clock import FrozenClock  # noqa: E402
from saas.config import Settings  # noqa: E402
from saas.container import Container  # noqa: E402
from saas.fake_astrbot import FakeAstrBot  # noqa: E402

ADMIN_EMAIL = "admin@example.com"


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(1_700_000_000)


@pytest.fixture
def port() -> FakeAstrBot:
    return FakeAstrBot()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.for_dev(tmp_path / "data")


@pytest.fixture
def container(settings: Settings, port: FakeAstrBot, clock: FrozenClock) -> Container:
    container = Container(settings, port=port, clock=clock)
    container.seed_defaults(admin_email=ADMIN_EMAIL)
    yield container
    container.close()


@pytest.fixture
def invite(container: Container) -> str:
    return container.invites.create(created_by="system", max_uses=1)["code"]


class ApiHelper:
    """Tiny API client wrapper that remembers the CSRF cookie."""

    def __init__(self, client) -> None:
        self.client = client

    @property
    def csrf(self) -> str:
        for cookie in self.client.session.cookie_jar:
            if cookie.key == "csrf":
                return cookie.value
        return ""

    @property
    def headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf} if self.csrf else {}

    async def login(self, email: str, invite: str | None = None) -> dict:
        payload = {"email": email}
        if invite:
            payload["invite"] = invite
        response = await self.client.post("/api/auth/otp/request", json=payload)
        body = await response.json()
        assert response.status == 200, body
        code = body["data"].get("dev_code")
        assert code, "dev OTP echo must be enabled in tests"
        verify_payload = {"email": email, "code": code}
        if invite:
            verify_payload["invite"] = invite
        response = await self.client.post(
            "/api/auth/otp/verify", json=verify_payload
        )
        body = await response.json()
        assert response.status == 200, body
        return body["data"]

    async def get(self, path: str):
        response = await self.client.get(path)
        return response, await response.json()

    async def post(self, path: str, json=None):
        response = await self.client.post(path, json=json, headers=self.headers)
        return response, await response.json()

    async def patch(self, path: str, json=None):
        response = await self.client.patch(path, json=json, headers=self.headers)
        return response, await response.json()

    async def put(self, path: str, json=None):
        response = await self.client.put(path, json=json, headers=self.headers)
        return response, await response.json()

    async def delete(self, path: str, json=None):
        response = await self.client.delete(path, json=json, headers=self.headers)
        return response, await response.json()


@pytest.fixture
async def api(container: Container):
    from aiohttp.test_utils import TestClient, TestServer

    from saas.web.app import create_app

    client = TestClient(TestServer(create_app(container)))
    await client.start_server()
    try:
        yield ApiHelper(client)
    finally:
        await client.close()


@pytest.fixture
async def user_api(api: ApiHelper, invite: str) -> ApiHelper:
    await api.login("user@example.com", invite=invite)
    return api


@pytest.fixture
async def admin_api(api: ApiHelper) -> ApiHelper:
    await api.login(ADMIN_EMAIL)
    return api
