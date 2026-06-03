"""Contract test DÙNG CHUNG cho mọi VectorRepository (conformance — MOSA §4).

Ép MỌI provider (qdrant, chromadb, milvus, plugin bên thứ ba) có CÙNG semantics ở các bất
biến backend-agnostic, chỉ qua port (upsert/hybrid_search/delete) — không đụng nội
bộ implementation:

  1. dimension guard      — upsert sai dimension -> ValueError (migration, không config)
  2. retrieve full content— search trả parent_text (full) cho LLM grounding
  3. idempotent           — re-upsert cùng chunk_id -> KHÔNG nhân đôi
  4. classification filter— secret cô lập theo department (block sai, cho phép đúng)
  5. delete_by_document   — xóa gỡ hết vector của document

Lưu ý: contract KHÔNG ghim chất lượng ranking hybrid-vs-dense (đó là *capability*
khác nhau giữa backend, không phải bất biến contract). Nó ghim những gì PHẢI giống.

    from haystack_interface.tests._contract import assert_vector_repository_contract
    await assert_vector_repository_contract(lambda s: MyRepo(s), dim=64)
"""

from __future__ import annotations

from typing import Callable

from app.domain.repositories.vector_repository import (
    UserContext,
    VectorRepository,
)

from haystack_interface.text_utils import hash_embed
from haystack_interface.vectorstore import VectorStoreConfig

ENG = UserContext(user_id="u-eng", user_role="user", user_department="engineering")
FIN = UserContext(user_id="u-fin", user_role="user", user_department="finance")


def _payload(document_id: str, classification: str, parent_text: str, **extra) -> dict:
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
        "classification": classification,
        "allowed_departments": extra.get("allowed_departments", []),
        "allowed_user_ids": extra.get("allowed_user_ids", []),
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
        await repo.upsert("bad::c0", [0.0] * (dim + 1), _payload("bad", "internal", "x"))
    except ValueError:
        raised = True
    assert raised, "[contract] upsert sai dimension phải raise ValueError"

    # 2. upsert + retrieve full content
    await repo.upsert("d-pw::p0::c0", pw_vec, _payload("d-pw", "internal", pw_text))
    res = await repo.hybrid_search(pw_vec, "reset mật khẩu", ENG, top_k=10)
    hit = [r for r in res if r.document_id == "d-pw"]
    assert hit, "[contract] search phải tìm được document vừa upsert"
    assert hit[0].parent_text, "[contract] phải trả parent_text (full content) cho LLM"

    # 3. idempotent — re-upsert cùng id không nhân đôi
    await repo.upsert("d-pw::p0::c0", pw_vec, _payload("d-pw", "internal", pw_text))
    res2 = await repo.hybrid_search(pw_vec, "reset mật khẩu", ENG, top_k=10)
    same_id = [r for r in res2 if r.chunk_id == "d-pw::p0::c0"]
    assert len(same_id) <= 1, f"[contract] re-upsert nhân đôi chunk_id: {len(same_id)}"

    # 4. classification filter — secret cô lập theo department
    await repo.upsert(
        "d-sal::p0::c0", sal_vec,
        _payload("d-sal", "secret", sal_text, allowed_departments=["finance"]),
    )
    blocked = await repo.hybrid_search(sal_vec, "ngân sách lương", ENG, top_k=10)
    assert all(r.document_id != "d-sal" for r in blocked), \
        "[contract] engineering KHÔNG được thấy secret của finance"
    allowed = await repo.hybrid_search(sal_vec, "ngân sách lương", FIN, top_k=10)
    assert any(r.document_id == "d-sal" for r in allowed), \
        "[contract] finance phải thấy secret của mình"

    # 5. delete_by_document gỡ hết vector
    await repo.delete_by_document("d-pw")
    after = await repo.hybrid_search(pw_vec, "reset mật khẩu", ENG, top_k=10)
    assert all(r.document_id != "d-pw" for r in after), \
        "[contract] delete_by_document phải gỡ hết vector của document"
