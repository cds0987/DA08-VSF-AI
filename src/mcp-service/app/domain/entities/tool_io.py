"""I/O contract của MCP tools.

Định nghĩa bởi SA — không sửa mà không có approval (xem docs/contracts.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ── rag_search ────────────────────────────────────────────────────────────────

@dataclass
class RagSearchInput:
    query: str
    document_ids: Optional[List[str]]  # inject từ ACL, None = chỉ public
    top_k: int = 5

