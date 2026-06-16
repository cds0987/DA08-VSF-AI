from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse


def _client_ip(request: Request) -> str | None:
    """IP gốc của client. Sau reverse-proxy (prod VM) thì lấy hop đầu của
    X-Forwarded-For; nếu không có thì dùng peer address."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None

_SSE_RESPONSES = {
    200: {
        "description": "Server-Sent Events stream. Each line: `data: <json>\\n\\n`. "
                       "Use EventSource (browser) or PowerShell (`Invoke-RestMethod` / `curl.exe -N`) — "
                       "Swagger UI cannot display SSE.",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}

_QUERY_DESCRIPTION = """\
Gửi câu hỏi, nhận phản hồi dạng **Server-Sent Events** (SSE).
Swagger UI không hiển thị được SSE — dùng PowerShell bên dưới để test.

**PowerShell native** (Invoke-RestMethod — in toàn bộ sau khi stream xong):
```powershell
$body = @{ question = "Tôi còn bao nhiêu ngày phép?"; user_id = "mock-user-hr" } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8001/query -Method Post `
  -Headers @{ Authorization = "Bearer mock-user-hr" } `
  -ContentType "application/json" -Body $body
```

**curl.exe -N** (xem realtime từng SSE event):
```powershell
$body = @{ question = "Tôi còn bao nhiêu ngày phép?"; user_id = "mock-user-hr" } | ConvertTo-Json
$bodyPath = Join-Path $env:TEMP "q.json"
$body | Set-Content -LiteralPath $bodyPath -NoNewline -Encoding utf8
curl.exe -N -X POST http://localhost:8001/query `
  -H "Authorization: Bearer mock-user-hr" `
  -H "Content-Type: application/json" `
  --data "@$bodyPath"
```
"""

from app.application.ports import AuthenticatedUser
from app.application.use_cases.query.orchestration import QueryOrchestrationUseCase
from app.infrastructure.cache.rate_limiter import RateLimiterUnavailable
from app.interfaces.api.dependencies import (
    get_conversation_repo,
    get_current_user,
    get_orchestration_use_case,
    get_rate_limiter,
)
from app.interfaces.api.schemas.query import QueryRequest
from app.interfaces.api.sse import format_sse

router = APIRouter(tags=["query"])


@router.post("/query", response_class=StreamingResponse, responses=_SSE_RESPONSES,
             description=_QUERY_DESCRIPTION)
async def query(
    request: QueryRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    use_case: QueryOrchestrationUseCase = Depends(get_orchestration_use_case),
    rate_limiter=Depends(get_rate_limiter),
    conversation_repo=Depends(get_conversation_repo),
    x_ci_smoke: str | None = Header(default=None),
) -> StreamingResponse:
    if request.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_id must match authenticated user",
        )

    # Rate-limit TRƯỚC mọi I/O (DB get_context, LLM) — spam không được chạm Postgres.
    try:
        allowed = await rate_limiter.allow(user.id, _client_ip(http_request))
    except RateLimiterUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter unavailable",
        ) from exc
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Max 20 requests/minute.",
        )

    if request.conversation_id:
        try:
            await conversation_repo.get_context(
                user.id,
                recent_k=0,
                conversation_id=str(request.conversation_id),
            )
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Conversation belongs to another user",
            ) from exc

    # Concurrency cap: chặn 1 user mở quá nhiều SSE/LLM stream song song (đốt token).
    try:
        slot = await rate_limiter.acquire(user.id)
    except RateLimiterUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter unavailable",
        ) from exc
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many concurrent requests for this user.",
        )

    # Smoke CI gửi header X-CI-Smoke=1 -> dán trace vào session "ci-smoke" (gom 1 chỗ,
    # deploy kế tự xóa). Query user thật KHÔNG có header -> session_id uuid bình thường.
    trace_session = "ci-smoke" if x_ci_smoke else request.trace_session

    async def events():
        try:
            async for event in use_case.stream(
                request.question,
                user,
                conversation_id=str(request.conversation_id) if request.conversation_id else None,
                trace_session=trace_session,
                conversation_title=request.conversation_title,
            ):
                yield format_sse(event)
        finally:
            # Trả slot khi stream kết thúc / client ngắt — release best-effort.
            await rate_limiter.release(user.id, slot)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
