"""M2 memory module: contract tests (InMemory vs SQLCipher), service, API, perf."""

from __future__ import annotations

import time

import pytest

from conftest import ApiHelper
from saas.memory.models import MemoryDraft, Turn
from saas.memory.service import MemoryService
from saas.memory.storage.in_memory import InMemoryRepository
from saas.memory.storage.repository import SqlCipherRepository
from saas.memory.storage.sqlcipher import MemoryStorage
from saas.memory.store import InMemoryStore

KEY = b"k" * 32


def _sqlcipher_repo(tmp_path) -> SqlCipherRepository:
    storage = MemoryStorage(tmp_path / "memory")
    storage.create_library("b_test", key=KEY, tenant_id="u_test")
    conn = storage.open_library("b_test", key=KEY)
    return SqlCipherRepository(conn)


@pytest.fixture(params=["in_memory", "sqlcipher"])
def repo(request, tmp_path):
    if request.param == "in_memory":
        return InMemoryRepository()
    return _sqlcipher_repo(tmp_path)


# ---------------------------------------------------------------- contract
def test_contract_add_get_update_delete(repo):
    memory_id = repo.add(
        MemoryDraft(content="用户喜欢深夜聊天", tags=["偏好", "作息"], importance=4),
        now=1000,
    )
    memory = repo.get(memory_id)
    assert memory is not None
    assert memory.content == "用户喜欢深夜聊天"
    assert set(memory.tags) == {"偏好", "作息"}
    assert memory.importance == 4

    memory.content = "用户喜欢凌晨聊天"
    memory.pinned = True
    memory.tags = ["作息"]
    memory.importance = 5
    repo.update(memory, now=2000)
    updated = repo.get(memory_id)
    assert updated.content == "用户喜欢凌晨聊天"
    assert updated.pinned is True
    assert updated.tags == ["作息"]
    assert updated.updated_at == 2000

    repo.soft_delete(memory_id, now=3000)
    assert repo.get(memory_id) is None
    assert repo.count() == 0


def test_contract_list_filters_and_pagination(repo):
    for index in range(5):
        repo.add(
            MemoryDraft(
                content=f"记忆{index}",
                kind="preference" if index % 2 else "fact",
                tags=["odd"] if index % 2 else ["even"],
                pinned=index == 0,
            ),
            now=1000 + index,
        )
    facts = repo.list(kind="fact")
    assert {memory.content for memory in facts} == {"记忆0", "记忆2", "记忆4"}
    tagged = repo.list(tag="odd")
    assert {memory.content for memory in tagged} == {"记忆1", "记忆3"}
    pinned_first = repo.list(limit=2)
    assert pinned_first[0].content == "记忆0"
    page2 = repo.list(cursor=pinned_first[-1].id, limit=10)
    assert len(page2) == 4


def test_contract_search_fts(repo):
    repo.add(MemoryDraft(content="用户住在杭州，做独立开发", tags=["地点"]), now=1000)
    repo.add(MemoryDraft(content="用户养了一只猫，叫豆豆", tags=["宠物"]), now=1001)
    hits = repo.search_fts("杭州", 10)
    assert len(hits) == 1
    assert "杭州" in hits[0].memory.content
    assert hits[0].score >= 0
    assert repo.search_fts("不存在的关键词", 10) == []
    # Tags are searchable too.
    assert repo.search_fts("宠物", 10)


def test_contract_touch_recalled(repo):
    memory_id = repo.add(MemoryDraft(content="常被回忆"), now=1000)
    repo.touch_recalled([memory_id], now=5000)
    memory = repo.get(memory_id)
    assert memory.recall_count == 1
    assert memory.last_recalled_at == 5000


def test_contract_duplicate_lookup(repo):
    repo.add(MemoryDraft(content="用户喜欢 咖啡"), now=1000)
    duplicate = repo.find_duplicate("用户喜欢咖啡", since=900)
    assert duplicate is not None
    assert repo.find_duplicate("用户喜欢咖啡", since=2000) is None


# ------------------------------------------------------------------ service
def _service(clock):
    store = InMemoryStore()
    return MemoryService(store, clock=clock, default_top_k=5), store


def test_service_dedupe_within_24h(clock):
    service, _ = _service(clock)
    first = service.remember("b1", MemoryDraft(content="用户喜欢咖啡"))
    assert first["created"] is True
    second = service.remember("b1", MemoryDraft(content="用户喜欢 咖啡！"))
    assert second["created"] is False
    assert second["duplicate"] is True
    clock.tick(86401)
    third = service.remember("b1", MemoryDraft(content="用户喜欢 咖啡！"))
    assert third["created"] is True


def test_service_validation(clock):
    service, _ = _service(clock)
    with pytest.raises(Exception):
        service.remember("b1", MemoryDraft(content="   "))
    with pytest.raises(Exception):
        service.remember("b1", MemoryDraft(content="x" * 5000))


async def test_service_recall_prefers_pinned_and_filters_kind(clock):
    service, _ = _service(clock)
    service.remember("b1", MemoryDraft(content="用户喜欢猫", kind="preference", importance=2))
    service.remember("b1", MemoryDraft(content="用户喜欢猫粮品牌 A", kind="note", pinned=True))
    recalled = await service.recall("b1", "用户喜欢猫")
    assert recalled, "should recall something"
    assert recalled[0].pinned is True
    only_notes = await service.recall("b1", "用户喜欢猫", kind="note")
    assert all(memory.kind == "note" for memory in only_notes)
    assert "记忆" in MemoryService.format_for_prompt(recalled)


def test_service_list_update_delete_export(clock):
    service, _ = _service(clock)
    result = service.remember("b1", MemoryDraft(content="导出测试", tags=["x"]))
    memory_id = result["memory"]["id"]
    listed = service.list("b1")
    assert listed["total"] == 1
    updated = service.update("b1", memory_id, {"content": "改名了", "pinned": True})
    assert updated.content == "改名了" and updated.pinned is True
    exported = service.export("b1")
    assert exported["count"] == 1
    service.delete("b1", memory_id)
    assert service.list("b1")["total"] == 0


async def test_command_extractor(clock):
    from saas.memory.extraction.command import CommandExtractor

    extractor = CommandExtractor()
    drafts = await extractor.extract(
        [
            Turn(role="user", content="/记住 用户周五下午要开会 #工作 kind:event importance:4"),
            Turn(role="assistant", content="好的"),
        ],
        max_items=3,
    )
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.kind == "event"
    assert draft.importance == 4
    assert "工作" in draft.tags
    assert "周五" in draft.content


# ---------------------------------------------------------- SQLCipher + 租户
async def test_sqlcipher_memory_file_is_encrypted(container, invite):
    import sqlite3

    code = container.auth.request_otp("mem@example.com", invite=invite)["dev_code"]
    user = container.auth.verify_otp("mem@example.com", code, invite=invite)["user"]
    template = container.templates.list(enabled_only=True)[0]
    bot = await container.bots.create(
        user_id=user["id"], name="记忆Bot", template_id=template["id"], platform="weixin_oc"
    )
    item = container.memory_api.remember(
        bot["id"], "用户偏好：每周三晚上复盘", kind="preference", tags=["复盘"]
    )
    assert item["created"] is True
    path = container.settings.memory_dir / f"{bot['id']}.db"
    assert path.exists()
    assert not path.read_bytes()[:16].startswith(b"SQLite format 3")
    with pytest.raises(sqlite3.DatabaseError):
        conn = sqlite3.connect(path)
        conn.execute("SELECT * FROM memories").fetchall()
    recalled = await container.memory_api.recall(bot["id"], "复盘")
    assert recalled and recalled[0]["content"].startswith("用户偏好")
    # connection cached and closed on bot delete
    assert bot["id"] in container.memory_store._repos
    await container.bots.delete(
        user_id=user["id"], bot_id=bot["id"], confirm_name="记忆Bot"
    )
    assert bot["id"] not in container.memory_store._repos
    assert not path.exists()


async def test_memory_isolated_between_bots(container, invite):
    code = container.auth.request_otp("iso@example.com", invite=invite)["dev_code"]
    user = container.auth.verify_otp("iso@example.com", code, invite=invite)["user"]
    template = container.templates.list(enabled_only=True)[0]
    bot_a = await container.bots.create(
        user_id=user["id"], name="A", template_id=template["id"], platform="weixin_oc"
    )
    bot_b = await container.bots.create(
        user_id=user["id"], name="B", template_id=template["id"], platform="weixin_oc"
    )
    container.memory_api.remember(bot_a["id"], "A 的私密记忆")
    assert container.memory_api.list(bot_a["id"])["total"] == 1
    assert container.memory_api.list(bot_b["id"])["total"] == 0
    assert await container.memory_api.recall(bot_b["id"], "私密") == []


# ------------------------------------------------------------------ HTTP API
async def _user_and_bot(api: ApiHelper):
    await api.login("memapi@example.com", invite=None) if False else None
    _, body = await api.get("/api/templates")
    template_id = body["data"]["items"][0]["id"]
    _, body = await api.post(
        "/api/bots",
        json={"name": "记忆 API", "template_id": template_id, "platform": "weixin_oc"},
    )
    return body["data"]["bot"]


async def test_memory_api_crud(user_api: ApiHelper, container):
    bot = await _user_and_bot(user_api)
    seeded = container.memory_api.remember(
        bot["id"], "用户是独立开发者", kind="fact", tags=["职业"], importance=5
    )
    memory_id = seeded["memory"]["id"]

    response, body = await user_api.get(f"/api/bots/{bot['id']}/memories")
    assert response.status == 200
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["kind_label"] == "事实"

    response, body = await user_api.get(
        f"/api/bots/{bot['id']}/memories?q=独立开发"
    )
    assert body["data"]["total"] == 1

    response, body = await user_api.get(
        f"/api/bots/{bot['id']}/memories/{memory_id}"
    )
    assert response.status == 200

    response, body = await user_api.patch(
        f"/api/bots/{bot['id']}/memories/{memory_id}",
        json={"content": "用户是自由职业开发者", "pinned": True},
    )
    assert response.status == 200
    assert body["data"]["memory"]["pinned"] is True

    response, body = await user_api.post(
        f"/api/bots/{bot['id']}/memories/search", json={"q": "自由职业"}
    )
    assert response.status == 200
    assert body["data"]["total"] == 1

    response, body = await user_api.post(
        f"/api/bots/{bot['id']}/memories/export"
    )
    assert response.status == 200
    assert body["data"]["count"] == 1

    response, body = await user_api.delete(
        f"/api/bots/{bot['id']}/memories/{memory_id}"
    )
    assert response.status == 200
    _, body = await user_api.get(f"/api/bots/{bot['id']}/memories")
    assert body["data"]["total"] == 0


async def test_memory_api_cross_tenant_404(api: ApiHelper, invite: str, container):
    await api.login("memowner@example.com", invite=invite)
    bot = await _user_and_bot(api)
    invite2 = container.invites.create(created_by="system", max_uses=1)["code"]
    await api.client.post("/api/auth/logout", headers=api.headers)
    await api.login("memother@example.com", invite=invite2)
    response, body = await api.get(f"/api/bots/{bot['id']}/memories")
    assert response.status == 404


# ------------------------------------------------------------------- perf
def test_fts_performance_10k(tmp_path):
    storage = MemoryStorage(tmp_path / "memory")
    storage.create_library("b_perf", key=KEY, tenant_id="u_perf")
    conn = storage.open_library("b_perf", key=KEY)
    now = 1_700_000_000
    rows = [
        (
            "fact",
            f"用户第{i}条记忆：喜欢在周末去西湖边散步，偶尔喝咖啡",
            "reason",
            3,
            0,
            "",
            "",
            "{}",
            now + i,
            now + i,
        )
        for i in range(10_000)
    ]
    from saas.memory.storage.repository import _index_text

    conn.executemany(
        "INSERT INTO memories(kind, content, reasoning, importance, pinned, "
        "source_conversation_id, source_message_id, metadata, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.executemany(
        "INSERT INTO memories_fts(rowid, content, reasoning, tags) VALUES (?,?,?,?)",
        [
            (index + 1, _index_text(row[1], row[2]), "", "")
            for index, row in enumerate(rows)
        ],
    )
    conn.commit()
    repo = SqlCipherRepository(conn)
    start = time.perf_counter()
    hits = repo.search_fts("西湖 咖啡", 50)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert len(hits) == 50
    assert elapsed_ms < 100, f"FTS over 10k rows took {elapsed_ms:.1f}ms"
    print(f"FTS 10k rows: {elapsed_ms:.1f}ms")
    conn.close()


def test_tenancy_umo_parsing():
    from saas.tenancy import parse_bot_id_from_umo, route_prefix

    assert parse_bot_id_from_umo("b_abc123:friend:session") == "b_abc123"
    assert parse_bot_id_from_umo("weixin_oc:friend:session") is None
    assert parse_bot_id_from_umo("b_") is None
    assert parse_bot_id_from_umo("") is None
    assert parse_bot_id_from_umo(None) is None
    assert route_prefix("b_abc") == "b_abc::"


async def test_llm_tool_dispatch():
    from saas.memory.api import MemoryAPI
    from saas.memory.service import MemoryService
    from saas.memory.store import InMemoryStore
    from saas.memory.tools.llm_tools import dispatch

    service = MemoryService(InMemoryStore())
    api = MemoryAPI(service)
    saved = await dispatch(
        api,
        "b1",
        "memory_remember",
        {"content": "用户喜欢喝乌龙茶", "kind": "preference", "tags": ["茶"]},
    )
    assert saved["created"] is True
    recalled = await dispatch(api, "b1", "memory_recall", {"query": "乌龙茶"})
    assert recalled["items"] and "乌龙茶" in recalled["items"][0]["content"]
    assert "[记忆]" in recalled["prompt"]
    await dispatch(api, "b1", "memory_forget", {"memory_id": saved["memory"]["id"]})
    assert api.list("b1")["total"] == 0
