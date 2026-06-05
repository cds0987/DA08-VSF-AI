"""Seed Qdrant bằng PRODUCER THẬT (rag-worker) cho e2e mcp-service.

Ingest 1 doc markdown (offline embed) + ghi dấu niêm contract vào Qdrant remote.
Dùng trong CI: rag-worker seed -> mcp-service đọc cùng Qdrant url.

Chạy: VECTOR_DB_URL=http://127.0.0.1:6333 AI_PROVIDER=offline \
      python scripts/seed_qdrant_e2e.py
"""

from __future__ import annotations

import asyncio

from core_engine.engine import IngestInput
from core_engine.factory import build_engine
from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.qdrant_contract import write_contract_stamp

MARKDOWN = (
    "# Phúc lợi\n\n"
    "Chính sách nghỉ phép thường niên 12 ngày cho nhân viên chính thức. "
    "Nhân viên có thể đăng ký nghỉ phép qua hệ thống nội bộ."
)


async def _run() -> None:
    vector_config = VectorStoreConfig.from_env()
    engine = build_engine(vector_config=vector_config)
    count = await engine.ingest(
        IngestInput(
            document_id="doc1",
            document_name="Sổ tay nhân viên",
            file_type="md",
            markdown=MARKDOWN,
            source_uri="gs://bucket/doc1.pdf",
            artifact_uri="gs://bucket/doc1.md",
        )
    )
    await write_contract_stamp(vector_config, written_by="rag-worker")
    print(
        f"seeded index={vector_config.index_id()} "
        f"fingerprint={vector_config.contract().fingerprint} chunks={count}"
    )


if __name__ == "__main__":
    asyncio.run(_run())
