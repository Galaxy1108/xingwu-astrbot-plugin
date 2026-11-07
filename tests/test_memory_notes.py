"""Angel-memory parity: note library, memory types/strength, export/import.

Covers targets 1, 2, 5 (and the note half of target 4):
* notes CRUD / short_id / tags / 分页读取 / standalone FTS (sqlite + in-memory)
* memory_type/strength/access_count/last_decay_at persistence + fact↔knowledge
* JSON snapshot export/import idempotency
* angel_memory import (memories incl. memory_records, tags relation, notes)
* legacy library migration to schema 004 on open
* LLM note tools dispatch + HTTP endpoints (note CRUD, read, ownership)
"""

from __future__ import annotations

import sqlite3

import pytest

from conftest import ApiHelper
from saas.clock import FrozenClock
from saas.memory.api import MemoryAPI
from saas.memory.export import export_snapshot, import_snapshot
from saas.memory.migration.from_angel import import_from_angel, inspect_source
from saas.memory.models import MemoryDraft
from saas.memory.notes import (
    MAX_READ_CHARS,
    NoteNotFoundError,
    NoteService,
    NoteValidationError,
    notes_repository_for,
)
from saas.memory.service import MemoryService
from saas.memory.storage.in_memory import InMemoryRepository
from saas.memory.storage.repository import SqlCipherRepository
from saas.memory.storage.sqlcipher import SCHEMA_DIR, MemoryStorage
from saas.memory.store import InMemoryStore
from saas.memory.tools.llm_tools import dispatch

KEY = b"k" * 32
START = 1_700_000_000


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(params=["in_memory", "sqlite"])
def notes_env(request, tmp_path):
    clock = FrozenClock(START)
    if request.param == "in_memory":
        repo = InMemoryRepository()
    else:
        storage = MemoryStorage(tmp_path / "memory", force_plaintext=True)
        storage.create_library("b_notes", key=KEY, tenant_id="u1")
        repo = SqlCipherRepository(storage.open_library("b_notes", key=KEY))
    return NoteService(notes_repository_for(repo), clock=clock), repo, clock


@pytest.fixture(params=["in_memory", "sqlite"])
def memory_repo(request, tmp_path):
    if request.param == "in_memory":
        return InMemoryRepository()
    storage = MemoryStorage(tmp_path / "memory", force_plaintext=True)
    storage.create_library("b_mem", key=KEY, tenant_id="u1")
    return SqlCipherRepository(storage.open_library("b_mem", key=KEY))


@pytest.fixture
async def notes_api(container, invite):
    from aiohttp.test_utils import TestClient, TestServer

    from saas.web import routes_memory_notes
    from saas.web.app import create_app

    app = create_app(container)
    # app.py auto-registers optional route modules; add them here only when a
    # checkout predates that wiring, so this test stays self-contained.
    existing = {route.resource.canonical for route in app.router.routes()}
    if "/api/bots/{bot_id}/notes" not in existing:
        app.add_routes(routes_memory_notes.routes)
    client = TestClient(TestServer(app))
    await client.start_server()
    helper = ApiHelper(client)
    await helper.login("notes@example.com", invite=invite)
    try:
        yield helper
    finally:
        await client.close()


async def _make_bot(api: ApiHelper) -> dict:
    _, body = await api.get("/api/templates")
    template_id = body["data"]["items"][0]["id"]
    _, body = await api.post(
        "/api/bots",
        json={"name": "笔记 Bot", "template_id": template_id, "platform": "weixin_oc"},
    )
    return body["data"]["bot"]


# ---------------------------------------------------------------------------
# notes: contract (sqlite + in-memory)
# ---------------------------------------------------------------------------
def test_note_create_short_id_get(notes_env):
    notes, _, clock = notes_env
    created = notes.create("Python 异步编程", "# 一、事件循环\n内容", tags=["Python", "异步"])
    short_id = created["short_id"]
    assert 6 <= len(short_id) <= 8
    assert all(ch in "23456789abcdefghjkmnpqrstuvwxyz" for ch in short_id)
    assert created["title"] == "Python 异步编程"
    assert created["tags"] == ["Python", "异步"]
    fetched = notes.get(short_id)
    assert fetched["content"].startswith("# 一、事件循环")
    # Lookup is case-insensitive and tolerates whitespace.
    assert notes.get(f"  {short_id.upper()} ")["short_id"] == short_id
    with pytest.raises(NoteNotFoundError):
        notes.get("zzzzzz")


def test_note_short_id_unique(notes_env):
    notes, _, _ = notes_env
    ids = {notes.create(f"标题{i}", f"正文{i}")["short_id"] for i in range(30)}
    assert len(ids) == 30


def test_note_list_pagination_and_tags(notes_env):
    notes, _, _ = notes_env
    for index in range(5):
        notes.create(
            f"笔记{index}",
            f"内容{index}",
            tags=["工作"] if index % 2 == 0 else ["生活"],
        )
    page = notes.list(page=1, page_size=2)
    assert page["total"] == 5
    assert len(page["items"]) == 2
    assert "content" not in page["items"][0]  # list is summary-only
    page3 = notes.list(page=3, page_size=2)
    assert len(page3["items"]) == 1
    work = notes.list(tag="工作")
    assert work["total"] == 3
    assert all("工作" in item["tags"] for item in work["items"])


def test_note_search_title_content_tags(notes_env):
    notes, _, _ = notes_env
    notes.create("Python 异步编程", "事件循环与协程", tags=["后端"])
    notes.create("咖啡笔记", "手冲参数记录", tags=["生活"])
    assert notes.search("异步")["total"] == 1
    assert notes.search("协程")["total"] == 1
    assert notes.search("后端")["total"] == 1
    assert notes.search("不存在的词")["total"] == 0
    # q + tag combine (FTS match + tag filter ordering).
    combined = notes.list(q="异步", tag="后端")
    assert combined["total"] == 1
    assert notes.list(q="异步", tag="生活")["total"] == 0


def test_note_read_pagination(notes_env):
    notes, _, _ = notes_env
    body = "0123456789" * 20  # 200 chars
    short_id = notes.create("长笔记", body)["short_id"]
    first = notes.read(short_id, offset=0, limit=80)
    assert first["content"] == body[:80]
    assert first["has_more"] is True
    assert first["next_offset"] == 80
    assert first["total_length"] == 200
    second = notes.read(short_id, offset=first["next_offset"], limit=80)
    assert second["content"] == body[80:160]
    tail = notes.read(short_id, offset=160, limit=80)
    assert tail["content"] == body[160:]
    assert tail["has_more"] is False
    assert tail["next_offset"] is None
    # Out-of-range offsets are clamped; limit is capped.
    beyond = notes.read(short_id, offset=10_000, limit=10)
    assert beyond["content"] == ""
    capped = notes.read(short_id, offset=0, limit=MAX_READ_CHARS * 2)
    assert capped["limit"] == MAX_READ_CHARS


def test_note_update_delete(notes_env):
    notes, _, _ = notes_env
    created = notes.create("旧标题", "旧正文", tags=["旧"])
    short_id = created["short_id"]
    updated = notes.update(short_id, {"title": "新标题", "content": "新正文", "tags": ["新"]})
    assert updated["title"] == "新标题"
    assert updated["content"] == "新正文"
    assert updated["tags"] == ["新"]
    assert notes.search("新正文")["total"] == 1
    notes.delete(short_id)
    assert notes.search("新正文")["total"] == 0  # FTS row removed
    with pytest.raises(NoteNotFoundError):
        notes.get(short_id)
    with pytest.raises(NoteNotFoundError):
        notes.delete(short_id)


def test_note_validation(notes_env):
    notes, _, _ = notes_env
    with pytest.raises(NoteValidationError):
        notes.create("标题", "   ")
    with pytest.raises(NoteValidationError):
        notes.create("标题", "正文", tags=[1, 2])
    created = notes.create("", "# 自动标题\n正文")
    assert created["title"] == "自动标题"


# ---------------------------------------------------------------------------
# memory types / strength contract (target 2)
# ---------------------------------------------------------------------------
def test_memory_kind_enum_parity():
    from saas.memory.models import KIND_LABELS, MemoryDraft, MemoryKind

    assert {kind.value for kind in MemoryKind} == {
        "knowledge",
        "preference",
        "relationship",
        "event",
        "emotion",
        "note",
    }
    assert MemoryKind.FACT.value == "knowledge"  # legacy alias, not new member
    assert KIND_LABELS["fact"] == "事实"  # old rows still render as 事实
    assert KIND_LABELS["knowledge"] == "知识"
    assert MemoryDraft(content="默认类型").kind == "knowledge"


def test_memory_strength_contract(memory_repo):
    memory_id = memory_repo.add(
        MemoryDraft(
            content="用户与阿澈是多年好友",
            kind="relationship",
            memory_type="relationship",
            strength=77,
            importance=5,
            tags=["人物"],
        ),
        now=START,
    )
    memory = memory_repo.get(memory_id)
    assert memory.memory_type == "relationship"
    assert memory.strength == 77
    assert memory.access_count == 0
    assert memory.last_decay_at == 0
    memory_repo.touch_recalled([memory_id], now=START + 10)
    recalled = memory_repo.get(memory_id)
    assert recalled.access_count == 1
    assert recalled.recall_count == 1
    memory_repo.apply_decay([(memory_id, 12)], now=START + 20)
    decayed = memory_repo.get(memory_id)
    assert decayed.strength == 12
    assert decayed.last_decay_at == START + 20
    # Strength is clamped to 0..100 on write.
    memory_id2 = memory_repo.add(MemoryDraft(content="越界强度", strength=900), now=START)
    assert memory_repo.get(memory_id2).strength == 100
    # to_dict exposes the angel-parity fields.
    payload = decayed.to_dict()
    assert payload["memory_type"] == "relationship"
    assert payload["strength"] == 12
    assert payload["access_count"] == 1


def test_kind_fact_knowledge_alias(memory_repo):
    fact_id = memory_repo.add(MemoryDraft(content="旧数据事实", kind="fact"), now=START)
    knowledge_id = memory_repo.add(
        MemoryDraft(content="新数据知识", kind="knowledge"), now=START + 1
    )
    fact = memory_repo.get(fact_id)
    assert fact.memory_type == "knowledge"  # legacy kind maps to the new type
    assert memory_repo.count(kind="knowledge") == 2
    assert memory_repo.count(kind="fact") == 2
    assert {m.id for m in memory_repo.list(kind="knowledge")} == {fact_id, knowledge_id}
    assert {hit.memory.id for hit in memory_repo.search_fts("数据", 10, kind="knowledge")} == {
        fact_id,
        knowledge_id,
    }
    assert memory_repo.search_fts("数据", 10, kind="preference") == []


def test_service_remember_passes_memory_type_and_strength(clock):
    service = MemoryService(InMemoryStore(), clock=clock)
    result = service.remember(
        "b1",
        MemoryDraft(
            content="用户对花生过敏",
            kind="knowledge",
            memory_type="event",
            strength=88,
        ),
    )
    memory = result["memory"]
    assert memory["memory_type"] == "event"
    assert memory["strength"] == 88
    updated = service.update("b1", memory["id"], {"strength": 5, "memory_type": "emotion"})
    assert updated.strength == 5
    assert updated.memory_type == "emotion"
    with pytest.raises(Exception):
        service.update("b1", memory["id"], {"memory_type": "unknown"})


# ---------------------------------------------------------------------------
# export / import snapshot (target 5)
# ---------------------------------------------------------------------------
def test_snapshot_export_import_idempotent(clock):
    service = MemoryService(InMemoryStore(), clock=clock)
    api = MemoryAPI(service)
    api.remember(
        "b_src",
        "用户喜欢喝乌龙茶",
        memory_type="preference",
        strength=82,
        tags=["饮食", "茶"],
        importance=4,
    )
    api.remember("b_src", "用户住在杭州", memory_type="knowledge", tags=["地点"])
    api.note_create("b_src", "茶笔记", "# 乌龙茶\n半发酵", tags=["茶"])

    snapshot = export_snapshot(
        service, "b_src", notes=api.note_service("b_src")
    )
    assert snapshot["version"] == 1
    assert snapshot["count"] == 2
    assert snapshot["notes_count"] == 1
    assert set(snapshot["tags"]) == {"饮食", "茶", "地点"}
    assert snapshot["memories"][0]["strength"] in {82, 50}

    first = import_snapshot(
        service, "b_dst", snapshot, notes=api.note_service("b_dst")
    )
    assert first["memories"]["imported"] == 2
    assert first["notes"]["imported"] == 1
    imported = api.list("b_dst", page_size=100)["items"]
    by_content = {item["content"]: item for item in imported}
    assert by_content["用户喜欢喝乌龙茶"]["memory_type"] == "preference"
    assert by_content["用户喜欢喝乌龙茶"]["strength"] == 82
    assert set(by_content["用户喜欢喝乌龙茶"]["tags"]) == {"饮食", "茶"}
    assert api.note_list("b_dst")["total"] == 1

    second = import_snapshot(
        service, "b_dst", snapshot, notes=api.note_service("b_dst")
    )
    assert second["memories"]["imported"] == 0
    assert second["memories"]["skipped"] == 2
    assert second["notes"]["imported"] == 0
    assert second["notes"]["skipped"] == 1
    assert api.list("b_dst", page_size=100)["total"] == 2
    assert api.note_list("b_dst")["total"] == 1


def test_snapshot_dry_run_writes_nothing(clock):
    service = MemoryService(InMemoryStore(), clock=clock)
    source = export_snapshot(service, "b_src")
    # Build a snapshot by hand so the source library is not shared.
    snapshot = {
        "version": 1,
        "memories": [
            {"content": "用户养了一只猫", "memory_type": "knowledge", "strength": 60},
            {"content": "用户养了一只狗", "kind": "fact"},
        ],
        "notes": [{"title": "宠物", "content": "猫和狗", "tags": ["宠物"]}],
    }
    api = MemoryAPI(service)
    report = import_snapshot(
        service, "b_dry", snapshot, notes=api.note_service("b_dry"), dry_run=True
    )
    assert report["memories"]["imported"] == 2
    assert report["notes"]["imported"] == 1
    assert service.list("b_dry")["total"] == 0
    assert api.note_list("b_dry")["total"] == 0
    assert source["count"] == 0


# ---------------------------------------------------------------------------
# import from angel_memory (target 5)
# ---------------------------------------------------------------------------
def _make_angel_db(path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE memory_records (
            id TEXT PRIMARY KEY, memory_type TEXT NOT NULL, judgment TEXT NOT NULL,
            reasoning TEXT NOT NULL, strength INTEGER NOT NULL, is_active INTEGER NOT NULL,
            useful_count INTEGER NOT NULL DEFAULT 0, useful_score REAL NOT NULL DEFAULT 0,
            last_recalled_at REAL NOT NULL DEFAULT 0, last_decay_at REAL NOT NULL DEFAULT 0,
            memory_scope TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE global_tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);
        CREATE TABLE memory_tag_rel (memory_id TEXT NOT NULL, tag_id INTEGER NOT NULL);
        CREATE TABLE notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT, tags TEXT
        );
        INSERT INTO memory_records(id, memory_type, judgment, reasoning, strength, is_active,
            memory_scope, created_at, updated_at)
        VALUES
            ('m1','情感记忆','用户今天很难过','被老板批评',5,0,'public',1,1),
            ('m2','知识记忆','用户在杭州做独立开发','',3,1,'public',2,2);
        INSERT INTO global_tags(name) VALUES ('情绪'), ('地点');
        INSERT INTO memory_tag_rel(memory_id, tag_id) VALUES ('m1', 1), ('m2', 2);
        INSERT INTO notes(title, content, tags) VALUES
            ('成长记录','# 成长\n今天学到很多','感悟,成长'),
            ('重复记录','# 成长\n今天学到很多','感悟');
        """
    )
    conn.commit()
    conn.close()


def test_import_from_angel_memories_and_notes(tmp_path, clock):
    source = tmp_path / "angel.db"
    _make_angel_db(source)
    info = inspect_source(source)
    assert "memory_records" in info["tables"] and "notes" in info["tables"]

    api = MemoryAPI(MemoryService(InMemoryStore(), clock=clock))
    report = import_from_angel(source, api, bot_id="b_angel")
    assert report["memory_table"] == "memory_records"
    assert report["note_table"] == "notes"
    assert report["imported"] == 2
    assert report["notes"]["imported"] == 1  # second note deduped by content
    assert report["notes"]["skipped"] == 1

    items = {item["content"]: item for item in api.list("b_angel", page_size=100)["items"]}
    emotion = items["用户今天很难过"]
    assert emotion["memory_type"] == "emotion"
    assert emotion["memory_type_label"] == "情感"
    assert emotion["strength"] == 50  # angel strength 5 → 50
    assert emotion["tags"] == ["情绪"]
    knowledge = items["用户在杭州做独立开发"]
    assert knowledge["memory_type"] == "knowledge"
    assert knowledge["pinned"] is True  # is_active → pinned (protected from decay)
    assert knowledge["tags"] == ["地点"]
    assert knowledge["metadata"]["imported_from"] == "angel_memory"
    notes = api.note_list("b_angel")["items"]
    assert len(notes) == 1
    assert notes[0]["title"] == "成长记录"
    assert set(notes[0]["tags"]) == {"感悟", "成长"}

    # Idempotent: a second run imports nothing new.
    second = import_from_angel(source, api, bot_id="b_angel")
    assert second["imported"] == 0
    assert second["skipped"] == 2
    assert second["notes"]["imported"] == 0
    assert api.list("b_angel", page_size=100)["total"] == 2
    assert api.note_list("b_angel")["total"] == 1


def test_import_from_angel_dry_run(tmp_path, clock):
    source = tmp_path / "angel.db"
    _make_angel_db(source)
    api = MemoryAPI(MemoryService(InMemoryStore(), clock=clock))
    report = import_from_angel(source, api, bot_id="b_angel", dry_run=True)
    assert report["imported"] == 2 and report["notes"]["imported"] == 1
    assert api.list("b_angel")["total"] == 0
    assert api.note_list("b_angel")["total"] == 0


# ---------------------------------------------------------------------------
# legacy library migration to schema 004 (on open)
# ---------------------------------------------------------------------------
def test_legacy_library_upgraded_on_open(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    path = memory_dir / "b_legacy.db"
    conn = sqlite3.connect(path)
    for name in ("001_init.sql", "002_fts.sql", "003_fts_standalone.sql"):
        conn.executescript((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    conn.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        [(1, START), (2, START), (3, START)],
    )
    conn.execute(
        "INSERT INTO memories(kind, content, reasoning, importance, created_at, updated_at) "
        "VALUES ('preference', '用户偏好深夜聊天', '', 4, ?, ?)",
        (START, START),
    )
    conn.commit()
    conn.close()

    storage = MemoryStorage(memory_dir, force_plaintext=True)
    repo = SqlCipherRepository(storage.open_library("b_legacy"))
    memory = repo.get(1)
    assert memory is not None
    assert memory.memory_type == "preference"  # backfilled from legacy kind
    assert memory.strength == 50
    assert memory.access_count == 0
    # 004 tables were created: notes are usable on the migrated library.
    notes = NoteService(notes_repository_for(repo))
    created = notes.create("迁移后笔记", "正文")
    assert notes.get(created["short_id"])["title"] == "迁移后笔记"
    # Migration version 4 recorded and re-open is idempotent.
    repo2 = SqlCipherRepository(storage.open_library("b_legacy"))
    assert repo2.get(1).memory_type == "preference"


def test_schema_004_applied_on_fresh_library(tmp_path):
    storage = MemoryStorage(tmp_path / "memory", force_plaintext=True)
    storage.create_library("b_fresh", key=KEY, tenant_id="u1")
    conn = sqlite3.connect(storage.path_for("b_fresh"))
    conn.row_factory = sqlite3.Row
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
    assert {"memory_type", "strength", "access_count", "last_decay_at"} <= columns
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"notes", "notes_fts", "memory_vectors"} <= tables
    versions = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
    assert 4 in versions
    conn.close()


# ---------------------------------------------------------------------------
# LLM tools dispatch (target 4)
# ---------------------------------------------------------------------------
async def test_llm_note_tools_dispatch(clock):
    api = MemoryAPI(MemoryService(InMemoryStore(), clock=clock))
    created = await dispatch(
        api,
        "b1",
        "memory_note_create",
        {"title": "调度测试", "content": "第一段\n第二段", "tags": ["工具"]},
    )
    assert created["short_id"]
    page = await dispatch(
        api,
        "b1",
        "memory_note_read",
        {"short_id": created["short_id"], "offset": 0, "limit": 3},
    )
    assert page["content"] == "第一段"
    assert page["has_more"] is True
    # memory_remember still accepts the legacy kind and the new fields.
    saved = await dispatch(
        api,
        "b1",
        "memory_remember",
        {
            "content": "用户是设计师",
            "memory_type": "relationship",
            "strength": 90,
            "tags": ["职业"],
        },
    )
    assert saved["memory"]["memory_type"] == "relationship"
    assert saved["memory"]["strength"] == 90
    legacy = await dispatch(
        api, "b1", "memory_remember", {"content": "用户喜欢猫", "kind": "fact"}
    )
    assert legacy["created"] is True
    assert legacy["memory"]["kind"] == "fact"
    assert legacy["memory"]["memory_type"] == "knowledge"


# ---------------------------------------------------------------------------
# HTTP endpoints (target 6; routes registered by the Lead in app.py)
# ---------------------------------------------------------------------------
async def test_notes_http_crud_and_read(notes_api: ApiHelper, container):
    bot = await _make_bot(notes_api)
    base = f"/api/bots/{bot['id']}/notes"

    response, body = await notes_api.post(
        base,
        json={
            "title": "HTTP 笔记",
            "content": "# 标题\n正文内容",
            "tags": ["接口"],
        },
    )
    assert response.status == 201, body
    short_id = body["data"]["note"]["short_id"]
    assert body["data"]["note"]["tags"] == ["接口"]

    response, body = await notes_api.get(base)
    assert response.status == 200
    assert body["data"]["total"] == 1

    response, body = await notes_api.get(f"{base}/{short_id}")
    assert response.status == 200
    assert body["data"]["note"]["content"].startswith("# 标题")

    response, body = await notes_api.get(f"{base}/{short_id}/read?offset=2&limit=4")
    assert response.status == 200
    assert body["data"]["offset"] == 2
    assert body["data"]["content"] == "标题\n正"

    response, body = await notes_api.get(f"{base}?q=接口")
    assert body["data"]["total"] == 1
    response, body = await notes_api.get(f"{base}?tag=接口")
    assert body["data"]["total"] == 1
    response, body = await notes_api.get(f"{base}?tag=不存在")
    assert body["data"]["total"] == 0

    response, body = await notes_api.patch(
        f"{base}/{short_id}", json={"title": "改后标题", "tags": ["新"]}
    )
    assert response.status == 200
    assert body["data"]["note"]["title"] == "改后标题"

    response, body = await notes_api.delete(f"{base}/{short_id}")
    assert response.status == 200
    _, body = await notes_api.get(base)
    assert body["data"]["total"] == 0

    # Unknown short_id / invalid pagination.
    response, body = await notes_api.get(f"{base}/zzzzzz")
    assert response.status == 404
    response, body = await notes_api.get(f"{base}?page=x")
    assert response.status == 400


async def test_notes_http_cross_tenant_404(notes_api: ApiHelper, container):
    bot = await _make_bot(notes_api)
    other_invite = container.invites.create(created_by="system", max_uses=1)["code"]
    await notes_api.client.post("/api/auth/logout", headers=notes_api.headers)
    await notes_api.login("notes-other@example.com", invite=other_invite)
    response, body = await notes_api.get(f"/api/bots/{bot['id']}/notes")
    assert response.status == 404
    response, body = await notes_api.post(
        f"/api/bots/{bot['id']}/notes", json={"title": "x", "content": "y"}
    )
    assert response.status == 404


async def test_consolidate_http_and_audit(notes_api: ApiHelper, container):
    bot = await _make_bot(notes_api)
    # Seed via the real service (clock is the frozen test clock).
    container.memory_api.remember(
        bot["id"], "用户喜欢喝咖啡", memory_type="preference", strength=60
    )
    url = f"/api/bots/{bot['id']}/memories/consolidate"
    response, body = await notes_api.post(url, json={"dry_run": True})
    assert response.status == 200, body
    assert body["data"]["dry_run"] is True
    assert body["data"]["scanned"] == 1

    response, body = await notes_api.post(url, json={})
    assert response.status == 200, body
    assert body["data"]["dry_run"] is False
    assert body["data"]["bot_id"] == bot["id"]

    audit = container.audit.list(action="memory.consolidated", target_id=bot["id"])
    assert audit["total"] == 2  # dry-run is audited too
    assert audit["items"][0]["detail"]["dry_run"] is False

    response, body = await notes_api.post(
        f"/api/bots/{bot['id']}/memories/consolidate", json={"dry_run": "yes"}
    )
    assert response.status == 200
    assert body["data"]["dry_run"] is True
