"""Append-migrate: model mới -> CREATE collection; model có rồi -> no-op; KHÔNG delete.

Tận dụng QdrantRemoteProvider._ensure (idempotent create-if-missing) làm cơ chế append.
Gác: (a) collection thiếu -> create gọi đúng 1 lần; (b) collection có -> create KHÔNG gọi;
(c) KHÔNG có path nào gọi delete_collection trong migrate (append-only).
"""
from __future__ import annotations

import importlib

import pytest


class _FakeClient:
    """AsyncQdrantClient giả: theo dõi create/delete; collection set khởi tạo = đã tồn tại."""

    def __init__(self, existing: set[str]) -> None:
        self._existing = set(existing)
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.indexed: list[str] = []

    async def collection_exists(self, name: str) -> bool:
        return name in self._existing

    async def create_collection(self, collection_name: str, **kwargs) -> None:
        self.created.append(collection_name)
        self._existing.add(collection_name)

    async def create_payload_index(self, collection_name: str, **kwargs) -> None:
        self.indexed.append(collection_name)

    async def delete_collection(self, name: str) -> None:
        self.deleted.append(name)


def _provider_with(existing: set[str], collection: str):
    from core_engine.vectorstore.config import VectorStoreConfig
    from core_engine.vectorstore.providers.qdrant import remote as remote_mod

    cfg = VectorStoreConfig(provider="qdrant", collection="rag_chatbot",
                            embed_model="baai/bge-m3", dimension=1024,
                            url="http://qdrant:6333")
    prov = remote_mod.QdrantRemoteProvider.__new__(remote_mod.QdrantRemoteProvider)
    # Bỏ qua __init__ (dựng client thật) -> set tay state tối thiểu cho _ensure.
    import asyncio
    prov.config = cfg
    prov._collection = collection
    prov._client = _FakeClient(existing)
    prov._ready = False
    prov._lock = asyncio.Lock()
    prov._upsert_batch = 256
    prov._mode = None
    return prov


@pytest.mark.asyncio
async def test_ensure_creates_missing_collection() -> None:
    prov = _provider_with(existing=set(), collection="rag_chatbot__bgem3__d1024")
    await prov._ensure()
    assert prov._client.created == ["rag_chatbot__bgem3__d1024"]
    assert prov._client.deleted == []  # APPEND: không xóa


@pytest.mark.asyncio
async def test_ensure_noop_when_collection_exists() -> None:
    name = "rag_chatbot__bgem3__d1024"
    prov = _provider_with(existing={name}, collection=name)
    await prov._ensure()
    assert prov._client.created == []   # đã có -> KHÔNG tạo lại
    assert prov._client.deleted == []   # KHÔNG xóa


def _load_migrate_module():
    import importlib.util
    import pathlib
    src = pathlib.Path(
        importlib.util.find_spec("core_engine").submodule_search_locations[0]
    ).parent / "scripts" / "multi_embed_migrate.py"
    spec = importlib.util.spec_from_file_location("multi_embed_migrate", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeColInfo:
    def __init__(self, points: int) -> None:
        self.points_count = points


class _FakeEnsureClient:
    """Client tối thiểu: collection_exists theo set existing + get_collection trả points
    (cho _collection_point_count -> backfill collection RỖNG)."""

    def __init__(self, existing: set[str], points: int = 0) -> None:
        self._existing = set(existing)
        self._points = points

    async def collection_exists(self, name: str) -> bool:
        return name in self._existing

    async def get_collection(self, name: str) -> _FakeColInfo:
        return _FakeColInfo(self._points)

    async def _ensure(self) -> None:  # provider._ensure giả (no-op create)
        return None


class _FakeProvider:
    def __init__(self, existing: set[str], collection: str, points: int = 0) -> None:
        self._client = _FakeEnsureClient(existing, points)
        self._collection = collection

    async def _ensure(self) -> None:
        return None


class _FakeVectors:
    def __init__(self, provider) -> None:
        self.provider = provider


class _FakeTarget:
    def __init__(self, collection: str, existing: set[str], points: int = 0) -> None:
        self.collection = collection
        self.embed_model = "fake/model"
        self.dimension = 1024
        self.vectors = _FakeVectors(_FakeProvider(existing, collection, points))


@pytest.mark.asyncio
async def test_ensure_collection_returns_created_for_missing() -> None:
    mod = _load_migrate_module()
    t = _FakeTarget("rag__new__d1024", existing=set())
    assert await mod._ensure_collection(t) == "created"


@pytest.mark.asyncio
async def test_ensure_collection_returns_exists_for_present() -> None:
    mod = _load_migrate_module()
    name = "rag__old__d1024"
    t = _FakeTarget(name, existing={name})
    assert await mod._ensure_collection(t) == "exists"


@pytest.mark.asyncio
async def test_backfill_new_only_backfills_created(monkeypatch) -> None:
    """--backfill-new: collection RỖNG (points=0) -> backfill; collection CÓ DATA -> SKIP.
    Robust với CI/CD: collection 'exists' nhưng RỖNG (create ở run trước) VẪN được backfill."""
    mod = _load_migrate_module()

    # RỖNG: exists=True (đã tạo run trước) NHƯNG points=0 -> PHẢI backfill (fix bug CI/CD).
    empty = _FakeTarget("rag__new__d1024", existing={"rag__new__d1024"}, points=0)
    populated = _FakeTarget("rag__old__d1024", existing={"rag__old__d1024"}, points=500)  # có data -> skip
    targets = [empty, populated]

    # build_embed_targets -> trả targets giả; bootstrap_runtime -> runtime giả tối thiểu.
    class _Cfg:
        def index_id(self) -> str:
            return "rag__primary__d4096"
        embed_model = "qwen/qwen3-embedding-8b"

    class _Engine:
        class vectors:  # noqa: N801
            config = _Cfg()
        settings = object()
        captioner = object()
        chunker = object()

    class _Runtime:
        engine = _Engine()
        document_repository = object()
        artifact_store = object()

    monkeypatch.setattr(mod, "bootstrap_runtime", lambda: _Runtime())
    monkeypatch.setattr(mod, "build_embed_targets", lambda *a, **k: targets)

    backfilled: list[str] = []

    async def _fake_backfill(*args, **kwargs):
        # target là tham số vị trí thứ 4 (sau settings, captioner, chunker)
        target = args[3]
        backfilled.append(target.collection)
        return (1, 0, 0)

    monkeypatch.setattr(mod, "_backfill_target", _fake_backfill)

    rc = await mod._run(dry_run=False, backfill=False, backfill_new=True, limit=None)
    assert rc == 0
    # CHỈ collection vừa created được backfill; collection exists bị SKIP.
    assert backfilled == ["rag__new__d1024"]


@pytest.mark.asyncio
async def test_backfill_new_noop_when_nothing_created(monkeypatch) -> None:
    """Deploy thường: mọi collection đã CÓ DATA (points>0) -> backfill-new NO-OP."""
    mod = _load_migrate_module()
    existing = _FakeTarget("rag__old__d1024", existing={"rag__old__d1024"}, points=500)

    class _Cfg:
        def index_id(self) -> str:
            return "rag__primary__d4096"
        embed_model = "qwen/qwen3-embedding-8b"

    class _Engine:
        class vectors:  # noqa: N801
            config = _Cfg()
        settings = object()
        captioner = object()
        chunker = object()

    class _Runtime:
        engine = _Engine()
        document_repository = object()
        artifact_store = object()

    monkeypatch.setattr(mod, "bootstrap_runtime", lambda: _Runtime())
    monkeypatch.setattr(mod, "build_embed_targets", lambda *a, **k: [existing])

    called = {"n": 0}

    async def _fake_backfill(*args, **kwargs):
        called["n"] += 1
        return (0, 0, 0)

    monkeypatch.setattr(mod, "_backfill_target", _fake_backfill)

    rc = await mod._run(dry_run=False, backfill=False, backfill_new=True, limit=None)
    assert rc == 0
    assert called["n"] == 0  # NO-OP: không backfill collection đã tồn tại


def test_migrate_script_has_no_delete_path() -> None:
    # Append-only bất biến: script migrate KHÔNG gọi delete_collection ở đâu cả.
    import pathlib
    src = pathlib.Path(
        importlib.util.find_spec("core_engine").submodule_search_locations[0]
    ).parent / "scripts" / "multi_embed_migrate.py"
    text = src.read_text(encoding="utf-8")
    assert "delete_collection" not in text
    assert "delete_by_document" not in text
