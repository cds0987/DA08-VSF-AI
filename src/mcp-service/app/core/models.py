"""Shared search types for mcp-service.

SearchHit là hình dạng ứng viên search dùng chung cho cả pipeline (rerank +
diversify) và _hit_to_dict (external tool contract). Trường map 1:1 với JSON
`candidates` mà rag-worker trả ở POST /api/search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class SearchHit:
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
