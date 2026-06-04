from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.application.ports import AuthenticatedUser
from app.application.use_cases.query.orchestration import QueryOrchestrationUseCase
from app.infrastructure.cache.rate_limiter import InMemoryRateLimiter
from app.interfaces.api.dependencies import (
    get_current_user,
    get_orchestration_use_case,
    get_rate_limiter,
)
from app.interfaces.api.schemas.query import QueryRequest
from app.interfaces.api.sse import format_sse

router = APIRouter(tags=["query"])


@router.post("/query")
async def query(
    request: QueryRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    use_case: QueryOrchestrationUseCase = Depends(get_orchestration_use_case),
    rate_limiter: InMemoryRateLimiter = Depends(get_rate_limiter),
) -> StreamingResponse:
    if request.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_id must match authenticated user",
        )
    if not rate_limiter.allow(user.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Max 20 requests/minute.",
        )

    async def events():
        async for event in use_case.stream(request.question, user):
            yield format_sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
