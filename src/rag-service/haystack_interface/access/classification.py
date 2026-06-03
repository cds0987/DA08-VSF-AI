"""Classification policy — NGUỒN SỰ THẬT DUY NHẤT cho access control.

Tách khỏi vector adapter (cohesion): adapter lo retrieval, policy lo "ai thấy gì".

Cùng một policy được dùng ở hai dạng biểu diễn:
- in-memory: predicate `can_access` (post-filter trên dict meta).
- Qdrant: pre-filter trên payload index — `vectorstore/qdrant.py` dựng Qdrant
  Filter TỪ CHÍNH các hằng ở đây (OPEN_CLASSIFICATIONS / *_FIELD / *_SCOPED), nên
  không drift về *tham số policy* dù khác cách biểu diễn.

public/internal → mở cho user đã xác thực; secret → đúng department; top_secret →
đúng user_id; admin → tất cả. (vector_repository docstring §filter)

> In-memory áp post-retrieval; production Qdrant PRE-FILTER trên payload index
> (search.md cảnh báo post-filter dễ mất kết quả).
"""

from __future__ import annotations

from app.domain.repositories.vector_repository import UserContext

# --- Policy parameters (single source) ------------------------------------- #
OPEN_CLASSIFICATIONS = ("public", "internal")  # mở cho mọi user đã xác thực
DEPT_SCOPED = "secret"                          # gate theo department
USER_SCOPED = "top_secret"                      # gate theo user_id
DEPARTMENT_FIELD = "allowed_departments"        # payload field chứa list department
USER_FIELD = "allowed_user_ids"                 # payload field chứa list user_id


def can_access(meta: dict, ctx: UserContext) -> bool:
    if ctx.user_role == "admin":
        return True
    classification = meta.get("classification", "internal")
    if classification in OPEN_CLASSIFICATIONS:
        return True  # caller đã xác thực user active trước khi vào đây
    if classification == DEPT_SCOPED:
        return ctx.user_department in (meta.get(DEPARTMENT_FIELD) or [])
    if classification == USER_SCOPED:
        return ctx.user_id in (meta.get(USER_FIELD) or [])
    return False
