from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.infrastructure.auth.auth_service import AuthenticatedUser
from app.infrastructure.db.mock_conversation_repo import InMemoryConversationRepository
from app.interfaces.api.dependencies import get_conversation_repo, require_admin
from app.interfaces.api.schemas.admin import AdminMetrics

router = APIRouter(tags=["admin"])


@router.get("/admin/metrics", response_model=AdminMetrics)
async def admin_metrics(
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    _: AuthenticatedUser = Depends(require_admin),
    repo: InMemoryConversationRepository = Depends(get_conversation_repo),
) -> dict:
    return await repo.metrics(from_date=from_date, to_date=to_date)
