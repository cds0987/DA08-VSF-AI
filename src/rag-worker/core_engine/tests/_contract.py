"""Contract test DÙNG CHUNG cho mọi VectorRepository (conformance — MOSA §4).

Ép MỌI provider (qdrant, chromadb, milvus, plugin bên thứ ba) có CÙNG semantics ở các bất
biến backend-agnostic, chỉ qua port (upsert/list/delete) — không đụng nội bộ
implementation. rag-worker = INGEST-ONLY: contract chỉ ghim mặt ghi (search là việc
của mcp-service), nên nghiệm thu qua `list_chunk_ids_by_document`:

  1. dimension guard      — upsert sai dimension -> ValueError (migration, không config)
  2. upsert ghi được      — chunk vừa upsert phải liệt kê được theo document
  3. idempotent           — re-upsert cùng chunk_id -> KHÔNG nhân đôi
  4. delete_by_document   — xóa gỡ hết vector của document

    from core_engine.tests._contract import assert_vector_repository_contract
    await assert_vector_repository_contract(lambda s: MyRepo(s), dim=64)
"""

from __future__ import annotations

from typing import Callable

from app.domain.repositories.vector_repository import VectorRepository

from core_engine.text_utils import hash_embed
from core_engine.vectorstore import VectorStoreConfig


def _payload(document_id: str, parent_text: str) -> dict:
    return {
        "child_text": parent_text,
        "bm25_text": parent_text,
        "parent_id": f"{document_id}::p0",
        "parent_text": parent_text,
        "document_id": document_id,
        "document_name": document_id,
        "file_type": "md",
        "page_number": 1,
        "section_title": "T",
    }


async def assert_vector_repository_contract(
    make_repo: Callable[[VectorStoreConfig], VectorRepository], dim: int = 64
) -> None:
    config = VectorStoreConfig(dimension=dim)
    repo = make_repo(config)

    pw_text = "reset mật khẩu vào cài đặt bảo mật link hết hạn 15 phút"
    sal_text = "ngân sách lương quý 2 tăng 8 phần trăm cho toàn bộ phòng ban"
    pw_vec = hash_embed([pw_text], dim)[0]
    sal_vec = hash_embed([sal_text], dim)[0]

    # 1. dimension guard
    raised = False
    try:
        await repo.upsert("bad::c0", [0.0] * (dim + 1), _payload("bad", "x"))
    except ValueError:
        raised = True
    assert raised, "[contract] upsert sai dimension phải raise ValueError"

    # 2. upsert ghi được — liệt kê chunk theo document
    await repo.upsert("d-pw::p0::c0", pw_vec, _payload("d-pw", pw_text))
    ids = await repo.list_chunk_ids_by_document("d-pw")
    assert "d-pw::p0::c0" in ids, "[contract] chunk vừa upsert phải liệt kê được"

    # 3. idempotent — re-upsert cùng id không nhân đôi
    await repo.upsert("d-pw::p0::c0", pw_vec, _payload("d-pw", pw_text))
    ids2 = await repo.list_chunk_ids_by_document("d-pw")
    same_id = [c for c in ids2 if c == "d-pw::p0::c0"]
    assert len(same_id) == 1, f"[contract] re-upsert nhân đôi chunk_id: {len(same_id)}"

    # 4. delete_by_document gỡ hết vector
    await repo.upsert("d-sal::p0::c0", sal_vec, _payload("d-sal", sal_text))
    await repo.delete_by_document("d-pw")
    after = await repo.list_chunk_ids_by_document("d-pw")
    assert not after, "[contract] delete_by_document phải gỡ hết vector của document"
