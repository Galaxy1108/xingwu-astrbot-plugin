"""Memory retrieval phase 2: embedding, vector store, RRF, rerank, settings API.

All upstream calls go to an in-process ``aiohttp`` test server; nothing here
touches the public network.
"""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from saas.memory.models import Memory, MemoryDraft
from saas.memory.retrieval.embedding import (
    EmbeddingClient,
    MemoryApiError,
    api_endpoint,
)
from saas.memory.retrieval.rerank import (
    RerankClient,
    RerankResult,
    parse_rerank_payload,
)
from saas.memory.service import (
    MASKED_API_KEY,
    MEMORY_SETTINGS_KEY,
    MemoryService,
    default_memory_settings,
    mask_memory_settings,
    normalize_memory_settings,
    reciprocal_rank_fusion,
)
from saas.memory.storage.repository import SqlCipherRepository
from saas.memory.storage.sqlcipher import MemoryStorage
from saas.memory.store import InMemoryStore, SqlCipherMemoryStore
import saas.memory.vector_store as vector_store_module
from saas.memory.vector_store import (
    MemoryVectorStore,
    VectorStoreError,
    cosine_similarity,
    pack_vector,
    unpack_vector,
)

KEY = b"k" * 32
SECRET = "sk-test-secret"


# --------------------------------------------------------------------------
# local upstream (embeddings + rerank)
# --------------------------------------------------------------------------
def _fake_embedding(text: str, dim: int = 8) -> list[float]:
    vector = [0.0] * dim
    for char in text:
        vector[ord(char) % dim] += 1.0
    vector[0] += 0.05  # keep empty strings non-zero
    return vector


@pytest.fixture
async def upstream():
    state: dict = {
        "base_url": "",
        "embedding_calls": [],
        "rerank_calls": [],
        "auth_headers": [],
        "embedding_status": 200,
        "rerank_status": 200,
        "rerank_shape": "results",
        "rerank_order": None,
    }

    async def embeddings(request: web.Request) -> web.Response:
        state["auth_headers"].append(request.headers.get("Authorization", ""))
        payload = await request.json()
        state["embedding_calls"].append(payload)
        if state["embedding_status"] >= 400:
            return web.json_response(
                {"error": f"upstream exploded {SECRET}"},
                status=state["embedding_status"],
            )
        dim = int(payload.get("dimensions") or 8)
        data = [
            {
                "object": "embedding",
                "index": index,
                "embedding": _fake_embedding(str(text), dim),
            }
            for index, text in enumerate(payload.get("input") or [])
        ]
        return web.json_response({"object": "list", "data": data})

    async def rerank(request: web.Request) -> web.Response:
        payload = await request.json()
        state["rerank_calls"].append(payload)
        if state["rerank_status"] >= 400:
            return web.json_response(
                {"error": f"rerank exploded {SECRET}"}, status=state["rerank_status"]
            )
        documents = payload.get("documents") or []
        order = state["rerank_order"] or list(range(len(documents)))
        if state["rerank_shape"] == "data":
            data = [
                {"index": index, "score": 1.0 - position * 0.1}
                for position, index in enumerate(order)
            ]
            return web.json_response({"data": data})
        results = [
            {"index": index, "relevance_score": 1.0 - position * 0.1}
            for position, index in enumerate(order)
        ]
        return web.json_response({"results": results})

    app = web.Application()
    app.router.add_post("/v1/embeddings", embeddings)
    app.router.add_post("/v1/rerank", rerank)
    client = TestClient(TestServer(app))
    await client.start_server()
    state["base_url"] = str(client.server.make_url("/")).rstrip("/")
    try:
        yield state
    finally:
        await client.close()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
class StaticSettingsStore:
    def __init__(self, raw: dict | None = None) -> None:
        self.raw = raw if raw is not None else {}

    def get(self, key: str, default=None):
        return self.raw if key == MEMORY_SETTINGS_KEY else default

    def set(self, key: str, value, *, actor_id: str = "") -> None:
        if key == MEMORY_SETTINGS_KEY:
            self.raw = value


def _memory_settings(
    base_url: str,
    *,
    embedding: bool = True,
    rerank: bool = False,
    behavior: dict | None = None,
) -> dict:
    raw = default_memory_settings()
    raw["embedding"].update(
        {
            "enabled": embedding,
            "base_url": base_url,
            "api_key": SECRET,
            "model": "test-embed",
            "dimensions": 8,
            "timeout_seconds": 5,
            "batch_size": 8,
        }
    )
    raw["rerank"].update(
        {
            "enabled": rerank,
            "base_url": base_url,
            "api_key": SECRET,
            "model": "test-rerank",
            "top_n": 10,
            "timeout_seconds": 5,
        }
    )
    if behavior:
        raw["behavior"].update(behavior)
    return raw


def _sql_store(tmp_path, *bot_ids: str) -> SqlCipherMemoryStore:
    storage = MemoryStorage(tmp_path / "memory")
    for bot_id in bot_ids:
        storage.create_library(bot_id, key=KEY, tenant_id="u_test")
    return SqlCipherMemoryStore(storage, lambda bot_id: KEY)


def _repo(tmp_path, bot_id: str = "b_vector") -> SqlCipherRepository:
    storage = MemoryStorage(tmp_path / "memory")
    storage.create_library(bot_id, key=KEY, tenant_id="u_test")
    return SqlCipherRepository(storage.open_library(bot_id, key=KEY))


# --------------------------------------------------------------------------
# settings normalization / masking
# --------------------------------------------------------------------------
def test_normalize_memory_settings_is_tolerant_and_defaults():
    raw = {
        "embedding": {"enabled": "true", "dimensions": "9999", "timeout_seconds": 0},
        "behavior": {"rrf_k": 500, "recall_top_k": "7", "unknown": 1},
        "unknown_section": {"x": 1},
    }
    settings = normalize_memory_settings(raw)
    assert settings["embedding"]["enabled"] is True
    assert settings["embedding"]["dimensions"] == 8192  # clamped
    assert settings["embedding"]["timeout_seconds"] == 1  # clamped
    assert settings["behavior"]["rrf_k"] == 100
    assert settings["behavior"]["recall_top_k"] == 7
    assert "unknown" not in settings["behavior"]
    assert "unknown_section" not in settings
    # normalize never mutates the defaults
    assert default_memory_settings()["embedding"]["dimensions"] == 1536


def test_mask_memory_settings_hides_key_and_reports_presence():
    masked = mask_memory_settings(
        {"embedding": {"api_key": SECRET}, "rerank": {"api_key": ""}}
    )
    assert masked["embedding"]["api_key"] == MASKED_API_KEY
    assert masked["embedding"]["has_api_key"] is True
    assert masked["rerank"]["api_key"] == ""
    assert masked["rerank"]["has_api_key"] is False


# --------------------------------------------------------------------------
# embedding client
# --------------------------------------------------------------------------
def test_api_endpoint_appends_v1():
    assert (
        api_endpoint("https://api.openai.com", "embeddings")
        == "https://api.openai.com/v1/embeddings"
    )
    assert (
        api_endpoint("https://api.openai.com/v1/", "embeddings")
        == "https://api.openai.com/v1/embeddings"
    )
    assert (
        api_endpoint("https://host/custom/v1/embeddings", "embeddings")
        == "https://host/custom/v1/embeddings"
    )


async def test_embedding_client_batches_and_sends_bearer(upstream):
    client = EmbeddingClient(
        base_url=upstream["base_url"],
        api_key=SECRET,
        model="test-embed",
        dimensions=8,
        batch_size=2,
        timeout_seconds=5,
    )
    try:
        vectors = await client.embed(["一", "二", "三"])
    finally:
        await client.close()

    assert len(vectors) == 3
    assert all(len(vector) == 8 for vector in vectors)
    assert len(upstream["embedding_calls"]) == 2
    assert upstream["embedding_calls"][0]["input"] == ["一", "二"]
    assert upstream["embedding_calls"][0]["model"] == "test-embed"
    assert upstream["auth_headers"][0] == f"Bearer {SECRET}"


async def test_embedding_client_accepts_v1_base_url(upstream):
    client = EmbeddingClient(
        base_url=upstream["base_url"] + "/v1/",
        api_key="",
        model="test-embed",
        dimensions=4,
    )
    try:
        vector = await client.embed_one("hello")
    finally:
        await client.close()
    assert len(vector) == 4


async def test_embedding_client_normalizes_http_errors(upstream):
    upstream["embedding_status"] = 401
    client = EmbeddingClient(
        base_url=upstream["base_url"], api_key=SECRET, model="test-embed"
    )
    try:
        with pytest.raises(MemoryApiError) as info:
            await client.embed(["x"])
    finally:
        await client.close()
    assert info.value.status == 401
    assert info.value.code == "upstream_error"
    assert SECRET not in info.value.public_message()


# --------------------------------------------------------------------------
# rerank client
# --------------------------------------------------------------------------
def test_parse_rerank_payload_variants():
    results = parse_rerank_payload(
        {
            "results": [
                {"index": 1, "relevance_score": 0.2},
                {"index": 0, "relevance_score": 0.8},
            ]
        },
        2,
    )
    assert [result.index for result in results] == [0, 1]
    assert results[0] == RerankResult(index=0, score=0.8)

    data = parse_rerank_payload({"data": [{"index": 1, "score": 0.5}]}, 2)
    assert data == [RerankResult(index=1, score=0.5)]

    assert parse_rerank_payload({"results": []}, 2) == []
    with pytest.raises(MemoryApiError):
        parse_rerank_payload({"oops": []}, 2)


async def test_rerank_client_parses_both_shapes(upstream):
    client = RerankClient(
        base_url=upstream["base_url"],
        api_key=SECRET,
        model="test-rerank",
        top_n=2,
        timeout_seconds=5,
    )
    try:
        results = await client.rerank("q", ["a", "b", "c"])
        assert [result.index for result in results] == [0, 1, 2]
        assert upstream["rerank_calls"][0]["documents"] == ["a", "b", "c"]
        assert upstream["rerank_calls"][0]["top_n"] == 2

        upstream["rerank_shape"] = "data"
        upstream["rerank_order"] = [2, 0]
        results = await client.rerank("q", ["a", "b", "c"])
        assert [result.index for result in results] == [2, 0]
    finally:
        await client.close()


async def test_rerank_client_normalizes_http_errors(upstream):
    upstream["rerank_status"] = 500
    client = RerankClient(
        base_url=upstream["base_url"], api_key=SECRET, model="test-rerank"
    )
    try:
        with pytest.raises(MemoryApiError) as info:
            await client.rerank("q", ["a"])
    finally:
        await client.close()
    assert info.value.status == 500
    assert SECRET not in info.value.public_message()


# --------------------------------------------------------------------------
# vector store
# --------------------------------------------------------------------------
def test_vector_pack_unpack_roundtrip():
    blob = pack_vector([0.5, -1.25, 3.0])
    assert len(blob) == 12  # float32
    assert unpack_vector(blob) == pytest.approx([0.5, -1.25, 3.0])
    with pytest.raises(VectorStoreError):
        unpack_vector(blob, dim=2)
    with pytest.raises(VectorStoreError):
        pack_vector([])


def test_cosine_similarity_numpy_and_pure_python(monkeypatch):
    assert cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([], [1, 0]) == 0.0
    assert cosine_similarity([0, 0], [1, 0]) == 0.0

    monkeypatch.setattr(vector_store_module, "_np", None)
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([1, 2], [1, 2]) == pytest.approx(1.0)


def test_vector_store_crud_search_and_filters(tmp_path):
    repo = _repo(tmp_path)
    first = repo.add(MemoryDraft(content="记忆一", kind="fact"), now=1000)
    second = repo.add(MemoryDraft(content="记忆二", kind="preference"), now=1001)
    store = MemoryVectorStore(repo)

    store.upsert(first, [1.0, 0.0, 0.0, 0.0], model="m1", now=100)
    store.upsert(second, [0.0, 1.0, 0.0, 0.0], model="m1", now=101)
    record = store.get(first)
    assert record is not None
    assert record.model == "m1"
    assert record.dim == 4
    assert record.vector == pytest.approx([1.0, 0.0, 0.0, 0.0])
    assert record.updated_at == 100
    assert store.count() == 2

    hits = store.search([1.0, 0.0, 0.0, 0.0], 10, model="m1")
    assert hits[0].memory_id == first
    assert hits[0].score == pytest.approx(1.0)
    assert [hit.memory_id for hit in store.search([1.0, 0, 0, 0], 10, kind="preference")] == [
        second
    ]
    assert store.search([1.0, 0, 0, 0], 10, model="other") == []

    # dimension mismatch rows are ignored, not compared
    store.upsert(first, [1.0, 0.0, 0.0], model="m2", now=200)
    assert store.search([1.0, 0.0, 0.0, 0.0], 10, model="m2") == []

    store.upsert(first, [0.0, 0.0, 1.0, 0.0], model="m1", now=201)
    assert store.get(first).vector == pytest.approx([0.0, 0.0, 1.0, 0.0])
    assert store.delete(first) is True
    assert store.get(first) is None
    assert store.delete(first) is False
    repo.conn.close()


# --------------------------------------------------------------------------
# RRF
# --------------------------------------------------------------------------
def test_reciprocal_rank_fusion():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 4]], k=60)
    assert [memory_id for memory_id, _ in fused] == [3, 1, 4, 2]
    scores = dict(fused)
    assert scores[3] == pytest.approx(1 / 63 + 1 / 61)
    assert scores[1] == pytest.approx(1 / 61)
    # k clamps to a sane positive integer
    assert reciprocal_rank_fusion([[1], [1]], k=0)[0][0] == 1


# --------------------------------------------------------------------------
# MemoryService: legacy / injection
# --------------------------------------------------------------------------
def _memory(memory_id: int, content: str) -> Memory:
    return Memory(id=memory_id, content=content)


async def test_recall_without_settings_keeps_legacy_behavior(clock):
    service = MemoryService(InMemoryStore(), clock=clock)
    service.remember("b1", MemoryDraft(content="用户喜欢猫", kind="preference"))
    service.remember(
        "b1", MemoryDraft(content="用户喜欢猫粮品牌 A", kind="note", pinned=True)
    )
    recalled = await service.recall("b1", "用户喜欢猫")
    assert recalled
    assert recalled[0].pinned is True


async def test_recall_accepts_injected_retrievers(clock):
    class FakeRetriever:
        def __init__(self) -> None:
            self.calls = 0

        async def retrieve(self, ctx):
            self.calls += 1
            return [_memory(99, "注入的记忆")]

    retriever = FakeRetriever()
    service = MemoryService(InMemoryStore(), clock=clock)
    recalled = await service.recall("b1", "任意", retrievers=[retriever])
    assert [memory.id for memory in recalled] == [99]
    assert retriever.calls == 1


# --------------------------------------------------------------------------
# MemoryService: embedding / rerank / maintenance
# --------------------------------------------------------------------------
async def test_remember_update_delete_maintain_vectors(
    upstream, tmp_path, clock
):
    store = _sql_store(tmp_path, "b_sync")
    settings = StaticSettingsStore(_memory_settings(upstream["base_url"]))
    service = MemoryService(store, clock=clock, settings_store=settings)

    created = service.remember("b_sync", MemoryDraft(content="用户喜欢喝咖啡"))
    memory_id = created["memory"]["id"]
    await service.wait_for_vector_tasks()

    vector_store = MemoryVectorStore(service._repo("b_sync"))
    record = vector_store.get(memory_id)
    assert record is not None
    assert record.model == "test-embed"
    assert record.dim == 8
    original = list(record.vector)

    service.update("b_sync", memory_id, {"content": "用户喜欢喝乌龙茶"})
    await service.wait_for_vector_tasks()
    updated = vector_store.get(memory_id)
    assert updated is not None
    assert updated.vector != pytest.approx(original)

    service.delete("b_sync", memory_id)
    assert vector_store.get(memory_id) is None
    store.close_all()


async def test_embedding_recall_fuses_and_uses_query_vector(
    upstream, tmp_path, clock
):
    store = _sql_store(tmp_path, "b_hybrid")
    settings = StaticSettingsStore(_memory_settings(upstream["base_url"]))
    service = MemoryService(store, clock=clock, settings_store=settings)
    service.remember("b_hybrid", MemoryDraft(content="用户喜欢喝咖啡", kind="preference"))
    service.remember("b_hybrid", MemoryDraft(content="用户养了一只猫叫豆豆"))
    await service.wait_for_vector_tasks()

    repo = service._repo("b_hybrid")
    assert MemoryVectorStore(repo).count(model="test-embed") == 2
    calls_before = len(upstream["embedding_calls"])
    recalled = await service.recall("b_hybrid", "咖啡", top_k=2)
    assert recalled
    assert "咖啡" in recalled[0].content
    assert len(upstream["embedding_calls"]) > calls_before  # query was embedded
    store.close_all()


async def test_embedding_failure_falls_back_to_fts(upstream, tmp_path, clock):
    upstream["embedding_status"] = 500
    store = _sql_store(tmp_path, "b_fail")
    settings = StaticSettingsStore(_memory_settings(upstream["base_url"]))
    service = MemoryService(store, clock=clock, settings_store=settings)

    created = service.remember("b_fail", MemoryDraft(content="用户喜欢喝咖啡"))
    assert created["created"] is True  # embedding failure never blocks the write
    await service.wait_for_vector_tasks()
    assert MemoryVectorStore(service._repo("b_fail")).count() == 0

    recalled = await service.recall("b_fail", "咖啡")
    assert recalled
    assert "咖啡" in recalled[0].content
    store.close_all()


async def test_rerank_reorders_candidates(upstream, tmp_path, clock):
    store = _sql_store(tmp_path, "b_rerank")
    settings = StaticSettingsStore(
        _memory_settings(upstream["base_url"], embedding=False, rerank=True)
    )
    service = MemoryService(store, clock=clock, settings_store=settings)
    service.remember("b_rerank", MemoryDraft(content="用户喜欢水果苹果"))
    service.remember("b_rerank", MemoryDraft(content="用户喜欢水果香蕉"))

    fts_hits = service._repo("b_rerank").search_fts("水果", 50)
    assert len(fts_hits) == 2
    expected_first = fts_hits[-1].memory.id
    upstream["rerank_order"] = [1, 0]  # force reverse of the candidate order

    recalled = await service.recall("b_rerank", "水果", top_k=2)
    assert recalled[0].id == expected_first
    assert upstream["rerank_calls"]
    store.close_all()


async def test_rerank_failure_falls_back_to_rules(upstream, tmp_path, clock):
    upstream["rerank_status"] = 500
    store = _sql_store(tmp_path, "b_rerank_fail")
    settings = StaticSettingsStore(
        _memory_settings(upstream["base_url"], embedding=False, rerank=True)
    )
    service = MemoryService(store, clock=clock, settings_store=settings)
    service.remember(
        "b_rerank_fail",
        MemoryDraft(content="用户喜欢水果苹果", importance=1),
    )
    service.remember(
        "b_rerank_fail",
        MemoryDraft(content="用户喜欢水果香蕉", importance=5),
    )

    recalled = await service.recall("b_rerank_fail", "水果", top_k=2)
    assert recalled  # no exception, rules fallback produced results
    assert recalled[0].importance == 5
    store.close_all()


async def test_vectors_and_recall_isolated_between_bots(upstream, tmp_path, clock):
    store = _sql_store(tmp_path, "b_iso_a", "b_iso_b")
    settings = StaticSettingsStore(_memory_settings(upstream["base_url"]))
    service = MemoryService(store, clock=clock, settings_store=settings)
    service.remember("b_iso_a", MemoryDraft(content="A 的咖啡记忆"))
    await service.wait_for_vector_tasks()

    assert MemoryVectorStore(service._repo("b_iso_a")).count() == 1
    assert MemoryVectorStore(service._repo("b_iso_b")).count() == 0
    assert await service.recall("b_iso_b", "咖啡") == []
    assert await service.recall("b_iso_a", "咖啡")
    store.close_all()


# --------------------------------------------------------------------------
# admin settings HTTP API
# --------------------------------------------------------------------------
async def test_memory_settings_mask_merge_and_audit(admin_api, container, upstream):
    response, body = await admin_api.get("/api/admin/settings/memory")
    assert response.status == 200
    data = body["data"]
    assert data["embedding"]["enabled"] is False
    assert data["embedding"]["api_key"] == ""
    assert data["embedding"]["has_api_key"] is False
    assert data["embedding"]["dimensions"] == 1536
    assert data["behavior"]["rrf_k"] == 60

    response, body = await admin_api.put(
        "/api/admin/settings/memory",
        json={
            "embedding": {
                "enabled": True,
                "base_url": upstream["base_url"],
                "api_key": SECRET,
                "model": "test-embed",
                "dimensions": 8,
                "timeout_seconds": 5,
                "batch_size": 8,
            },
            "behavior": {"rrf_k": 42, "recall_top_k": 7},
        },
    )
    assert response.status == 200
    data = body["data"]
    assert data["embedding"]["api_key"] == MASKED_API_KEY
    assert data["embedding"]["has_api_key"] is True
    assert data["embedding"]["model"] == "test-embed"
    assert data["behavior"]["rrf_k"] == 42
    stored = container.settings_store.get(MEMORY_SETTINGS_KEY)
    assert stored["embedding"]["api_key"] == SECRET

    # Mask means "keep the stored key".
    response, body = await admin_api.put(
        "/api/admin/settings/memory",
        json={"embedding": {"api_key": MASKED_API_KEY, "model": "test-embed-2"}},
    )
    assert response.status == 200
    assert body["data"]["embedding"]["model"] == "test-embed-2"
    assert body["data"]["embedding"]["has_api_key"] is True
    assert (
        container.settings_store.get(MEMORY_SETTINGS_KEY)["embedding"]["api_key"]
        == SECRET
    )

    # Empty string clears the key.
    response, body = await admin_api.put(
        "/api/admin/settings/memory", json={"embedding": {"api_key": ""}}
    )
    assert response.status == 200
    assert body["data"]["embedding"]["api_key"] == ""
    assert body["data"]["embedding"]["has_api_key"] is False

    audits = container.audit.list(action="memory.settings_updated")
    assert audits["total"] >= 3
    assert SECRET not in json.dumps(audits["items"], ensure_ascii=False)


async def test_memory_settings_requires_admin(api, invite):
    await api.login("user@example.com", invite=invite)
    response, body = await api.get("/api/admin/settings/memory")
    assert response.status == 403
    assert body["error"]["code"] == "forbidden"
    response, _ = await api.put(
        "/api/admin/settings/memory", json={"behavior": {"rrf_k": 30}}
    )
    assert response.status == 403


async def test_memory_settings_test_endpoint(admin_api, upstream):
    response, _ = await admin_api.put(
        "/api/admin/settings/memory",
        json={
            "embedding": {
                "enabled": True,
                "base_url": upstream["base_url"],
                "api_key": SECRET,
                "model": "test-embed",
                "dimensions": 8,
                "timeout_seconds": 5,
                "batch_size": 8,
            },
            "rerank": {
                "enabled": True,
                "base_url": upstream["base_url"],
                "api_key": SECRET,
                "model": "test-rerank",
                "top_n": 2,
                "timeout_seconds": 5,
            },
        },
    )
    assert response.status == 200

    response, body = await admin_api.post(
        "/api/admin/settings/memory/test", json={"kind": "embedding"}
    )
    assert response.status == 200
    assert body["data"]["ok"] is True
    assert body["data"]["dim"] == 8

    response, body = await admin_api.post(
        "/api/admin/settings/memory/test", json={"kind": "rerank"}
    )
    assert response.status == 200
    assert body["data"]["ok"] is True
    assert body["data"]["count"] == 2

    # Upstream failure → sanitized 502 (no API key in the payload).
    upstream["embedding_status"] = 401
    response, body = await admin_api.post(
        "/api/admin/settings/memory/test", json={"kind": "embedding"}
    )
    assert response.status == 502
    assert body["ok"] is False
    assert body["error"]["code"] == "upstream_error"
    assert SECRET not in json.dumps(body, ensure_ascii=False)


async def test_container_service_uses_platform_settings_once_wired(
    admin_api, container, invite, upstream
):
    """Simulates the Lead's one-line wiring (service ← settings_store)."""
    container.memory_service.settings_store = container.settings_store
    response, _ = await admin_api.put(
        "/api/admin/settings/memory",
        json={
            "embedding": {
                "enabled": True,
                "base_url": upstream["base_url"],
                "api_key": SECRET,
                "model": "test-embed",
                "dimensions": 8,
                "timeout_seconds": 5,
                "batch_size": 8,
            }
        },
    )
    assert response.status == 200

    code = container.auth.request_otp("retrieval-wired@example.com", invite=invite)[
        "dev_code"
    ]
    user = container.auth.verify_otp(
        "retrieval-wired@example.com", code, invite=invite
    )["user"]
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"],
        name="检索Bot",
        template_id=template["id"],
        platform="weixin_oc",
    )
    container.memory_api.remember(bot["id"], "用户喜欢喝咖啡", kind="preference")
    await container.memory_service.wait_for_vector_tasks()

    recalled = await container.memory_api.recall(bot["id"], "咖啡")
    assert recalled
    assert "咖啡" in recalled[0]["content"]
    assert MemoryVectorStore(container.memory_store.open(bot["id"])).count() == 1
