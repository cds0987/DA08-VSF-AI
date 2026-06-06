"""Demo ingest-only chạy offline (không cần BGE-M3/Qdrant/Azure).

    python -m core_engine.demo

Ingest vài tài liệu rồi in ra payload đã được ghi vào vector store để thấy:
parse/section → caption/embed → upsert + lineage.
"""

from __future__ import annotations

import asyncio
import sys

# Console Windows mặc định cp1252 -> ép UTF-8 để in tiếng Việt.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core_engine import build_engine, IngestInput, OfflineProvider


DOCS = [
    IngestInput(
        document_id="doc-reset",
        document_name="Hướng dẫn tài khoản",
        file_type="md",
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
        markdown=(
            "# Lương quý 2\n"
            "Ngân sách lương quý 2 tăng 8 phần trăm so với quý 1, "
            "áp dụng từ tháng 6 cho toàn bộ phòng ban.\n"
        ),
    ),
]


async def main() -> None:
    # Offline (hash-embed) — không cần key/network.
    # caption=True: flow chuẩn embed *caption*. Đổi sang OpenAI: build_engine() khi có key.
    engine = build_engine(provider=OfflineProvider(256), caption=True)

    print("== INGEST ==")
    for d in DOCS:
        n = await engine.ingest(d)
        print(f"  {d.document_id:<12} -> {n} chunks")

    print("\n== VECTOR PAYLOADS ==")
    provider = engine.vectors.provider
    client = getattr(provider, "_client", None)
    if client is None:
        print("  provider does not expose a local client; payload inspection unavailable")
        return
    result = client.scroll(
        collection_name=engine.vectors.config.index_id(),
        with_payload=True,
        with_vectors=False,
        limit=1000,
    )
    points = result[0] if isinstance(result, tuple) else result
    for point in points:
        payload = point.payload or {}
        print(
            f"  {payload.get('document_id', '?'):<12} "
            f"{payload.get('section_title', '(no-title)')!s:<20} "
            f"source={payload.get('source_uri', '')}"
        )
        print(f"        {str(payload.get('parent_text', ''))[:80].strip()}...")


if __name__ == "__main__":
    asyncio.run(main())
