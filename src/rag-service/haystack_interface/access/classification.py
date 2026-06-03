"""Classification filter — policy access control theo UserContext.

Tách khỏi vector adapter (cohesion): adapter lo retrieval, policy lo "ai thấy gì".

public → mở; internal → user đã xác thực active; secret → đúng department;
top_secret → đúng user_id. Admin thấy tất cả. (vector_repository docstring §filter)

> In-memory: áp như predicate post-retrieval. Production Qdrant nên PRE-FILTER
> trên payload index (classification/allowed_departments/allowed_user_ids) —
> search.md cảnh báo post-filter dễ mất kết quả.
"""

from __future__ import annotations

from app.domain.repositories.vector_repository import UserContext


def can_access(meta: dict, ctx: UserContext) -> bool:
    if ctx.user_role == "admin":
        return True
    classification = meta.get("classification", "internal")
    if classification == "public":
        return True
    if classification == "internal":
        return True  # caller đã xác thực user active trước khi vào đây
    if classification == "secret":
        return ctx.user_department in (meta.get("allowed_departments") or [])
    if classification == "top_secret":
        return ctx.user_id in (meta.get("allowed_user_ids") or [])
    return False
