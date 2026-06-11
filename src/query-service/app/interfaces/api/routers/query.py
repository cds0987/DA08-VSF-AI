from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse

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
    user: AuthenticatedUser = Depends(get_current_user),
    use_case: QueryOrchestrationUseCase = Depends(get_orchestration_use_case),
    rate_limiter=Depends(get_rate_limiter),
    x_ci_smoke: str | None = Header(default=None),
) -> StreamingResponse:
    if request.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_id must match authenticated user",
        )
    try:
        allowed = await rate_limiter.allow(user.id)
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

    # Smoke CI gửi header X-CI-Smoke=1 -> dán trace vào session "ci-smoke" (gom 1 chỗ,
    # deploy kế tự xóa). Query user thật KHÔNG có header -> session_id uuid bình thường.
    trace_session = "ci-smoke" if x_ci_smoke else request.trace_session

    async def events():
        async for event in use_case.stream(request.question, user, trace_session=trace_session):
            yield format_sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
