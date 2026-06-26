from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping, Sequence


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    vector: Sequence[float]
    payload: Mapping[str, Any]
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)


@dataclass
class SearchHit:
    """Một ứng viên trả về từ vectorstore.search (payload + score, CHƯA rerank).

    Field mapping ĐỐI XỨNG với mcp-service _to_hit (app/core/vectorstore.py): caption
    fallback child_text; source_gcs_uri = payload "source_uri"; markdown_gcs_uri =
    payload "artifact_uri". Đây là 1-nguồn-sự-thật phía rag-worker khi query-side
    retrieval chuyển từ mcp về đây — caller (rerank) nhận đúng schema cũ.
    """

    chunk_id: str = ""
    document_id: str = ""
    document_name: str = ""
    caption: str = ""
    child_text: str = ""
    parent_text: str = ""
    heading_path: List[str] = field(default_factory=list)
    score: float = 0.0
    page_number: int | None = None
    source_gcs_uri: str = ""
    markdown_gcs_uri: str = ""
