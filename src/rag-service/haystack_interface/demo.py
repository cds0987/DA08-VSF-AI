"""Demo end-to-end chạy offline (không cần BGE-M3/Qdrant/Azure).

    python -m haystack_interface.demo

Ingest vài tài liệu (gồm cả secret) rồi search với 2 user khác nhau để thấy:
ingest → hybrid retrieval → rerank Top-3, và classification filter cô lập secret.
"""

from __future__ import annotations

import asyncio
import sys

# Console Windows mặc định cp1252 -> ép UTF-8 để in tiếng Việt.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.domain.repositories.vector_repository import UserContext

from haystack_interface import build_engine, IngestInput, OfflineProvider


DOCS = [
    IngestInput(
        document_id="doc-reset",
        document_name="Hướng dẫn tài khoản",
        file_type="md",
        classification="internal",
        markdown=(
            "# Reset mật khẩu\n"
            "Để reset mật khẩu, vào trang Cài đặt > Bảo mật, chọn Quên mật khẩu. "
            "Hệ thống gửi email chứa link đặt lại. Link hết hạn sau 15 phút.\n"
            "# Khóa tài khoản\n"
            "Sai mật khẩu 5 lần liên tiếp sẽ khóa tài khoản trong 30 phút.\n"
        ),
    ),
    IngestInput(
        document_id="doc-vectordb",
        document_name="Ghi chú Vector DB",
        file_type="md",
        classification="public",
        markdown=(
            "# Vector database\n"
            "Vector database lưu embedding và tìm theo độ gần ngữ nghĩa. "
            "Qdrant hỗ trợ filtering mạnh và payload index, hợp RAG metadata-heavy.\n"
            "# Distance metric\n"
            "Text embedding thường dùng cosine similarity, cần normalize vector.\n"
        ),
    ),
    IngestInput(
        document_id="doc-salary",
        document_name="Bảng lương Q2",
        file_type="md",
        classification="secret",
        allowed_departments=["finance"],
        markdown=(
            "# Lương quý 2\n"
            "Ngân sách lương quý 2 tăng 8 phần trăm so với quý 1, "
            "áp dụng từ tháng 6 cho toàn bộ phòng ban.\n"
        ),
    ),
]


async def main() -> None:
    # Offline (hash-embed + LLM-as-reranker giả lập) — không cần key/network.
    # caption=True: flow chuẩn embed *caption*. Đổi sang OpenAI: build_engine() khi có key.
    engine = build_engine(provider=OfflineProvider(256), caption=True)

    print("== INGEST ==")
    for d in DOCS:
        n = await engine.ingest(d)
        print(f"  {d.document_id:<12} [{d.classification:<9}] -> {n} chunks")

    # rerank_threshold=0.0 để thấy Top-3 (stub lexical; production BGE dùng 0.7).
    finance_user = UserContext(user_id="u1", user_role="user", user_department="finance")
    eng_user = UserContext(user_id="u2", user_role="user", user_department="engineering")

    async def show(query: str, ctx: UserContext, label: str) -> None:
        results = await engine.search(query, ctx, rerank_threshold=0.0)
        print(f"\n== SEARCH ({label}): {query!r} ==")
        if not results:
            print("  (no-answer)")
        for r in results:
            print(
                f"  [{r.rerank_score:.2f}] {r.document_name} / {r.section_title}"
                f"  (rrf={r.score:.4f})"
            )
            print(f"        {r.parent_text[:80].strip()}...")

    await show("làm sao để reset mật khẩu", eng_user, "engineering")
    await show("vector database dùng metric gì", eng_user, "public doc")
    # finance thấy secret bảng lương; engineering thì KHÔNG.
    await show("ngân sách lương quý 2 tăng bao nhiêu", finance_user, "finance → secret")
    await show("ngân sách lương quý 2 tăng bao nhiêu", eng_user, "engineering → bị chặn")


if __name__ == "__main__":
    asyncio.run(main())
