"""Self-test offline bằng assert (không cần pytest / network):

    python -m haystack_interface.selftest

Khóa các bất biến: embedder cùng dimension & tất định (ingest==query), ingest tạo
chunk, retrieval đúng tài liệu, classification filter cô lập secret, idempotent
(re-ingest không nhân đôi), delete gỡ hết vector, no-answer khi threshold cao.
"""

from __future__ import annotations

import asyncio

from app.domain.repositories.vector_repository import UserContext

from haystack_interface import build_engine, IngestInput, OfflineProvider
from haystack_interface.embedding import ProviderEmbeddingService

DIM = 256


async def run() -> None:
    provider = OfflineProvider(DIM)
    # caption=False => baseline embed child trực tiếp (tất định, dễ assert).
    engine = build_engine(provider=provider, caption=False)
    settings = engine.settings

    # 1. Embedder: đúng dimension, tất định (ingest==query).
    emb = ProviderEmbeddingService(provider, dimension=DIM)
    v1 = await emb.embed("reset mật khẩu")
    v2 = await emb.embed("reset mật khẩu")
    assert len(v1) == settings.embed_dimension == DIM, "sai dimension embed"
    assert v1 == v2, "embedder phải tất định (ingest==query)"

    # 2. Ingest tạo chunk.
    pw = IngestInput(
        document_id="d-pw", document_name="Account", file_type="md",
        classification="internal",
        markdown="# Reset mật khẩu\nVào Cài đặt > Bảo mật để đặt lại mật khẩu, link hết hạn 15 phút.\n",
    )
    n = await engine.ingest(pw)
    assert n >= 1, "ingest phải tạo >=1 chunk"

    await engine.ingest(IngestInput(
        document_id="d-sal", document_name="Salary", file_type="md",
        classification="secret", allowed_departments=["finance"],
        markdown="# Lương quý 2\nNgân sách lương quý 2 tăng 8 phần trăm.\n",
    ))

    user = UserContext(user_id="u1", user_role="user", user_department="engineering")
    fin = UserContext(user_id="u2", user_role="user", user_department="finance")

    # 3. Retrieval đúng tài liệu + trả full content cho LLM.
    res = await engine.search("reset mật khẩu", user, rerank_threshold=0.0)
    assert res, "search phải có kết quả"
    assert res[0].document_id == "d-pw", "kết quả top-1 sai tài liệu"
    assert res[0].parent_text, "phải trả full content (parent_text) cho LLM"

    # 4. Classification filter: secret cô lập theo department.
    blocked = await engine.search("ngân sách lương quý 2", user, rerank_threshold=0.0)
    assert all(r.document_id != "d-sal" for r in blocked), "engineering KHÔNG được thấy secret finance"
    allowed = await engine.search("ngân sách lương quý 2", fin, rerank_threshold=0.0)
    assert any(r.document_id == "d-sal" for r in allowed), "finance phải thấy secret của mình"

    # 5. Idempotent: re-ingest cùng doc KHÔNG nhân đôi (OVERWRITE + id deterministic).
    before = len(engine.vectors.store.filter_documents())
    await engine.ingest(pw)
    after = len(engine.vectors.store.filter_documents())
    assert before == after, f"re-ingest phải idempotent: {before} -> {after}"

    # 6. No-answer: threshold cao -> rỗng (không bịa).
    none = await engine.search("xyzzy không liên quan gì", user, rerank_threshold=0.99)
    assert none == [], "threshold cao phải cho no-answer, không trả kết quả yếu"

    # 7. delete_by_document gỡ hết vector.
    await engine.vectors.delete_by_document("d-pw")
    gone = await engine.search("reset mật khẩu", user, rerank_threshold=0.0)
    assert all(r.document_id != "d-pw" for r in gone), "xóa document phải gỡ hết vector"

    print("OK - all self-tests PASS")


if __name__ == "__main__":
    asyncio.run(run())
