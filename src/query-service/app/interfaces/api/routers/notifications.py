import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.application.ports import AuthenticatedUser
from app.domain.repositories.notification_repository import NotificationRepository
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.messaging.notification_service import DocNewEvent, NotificationService
from app.infrastructure.sse.connection_manager import ConnectionManager
from app.interfaces.api.dependencies import (
    get_connection_manager,
    get_current_user,
    get_notification_repo,
    get_notification_service,
    require_admin,
)
from app.interfaces.api.schemas.notification import (
    DocNewEventRequest,
    NotificationItem,
    NotificationList,
    UnreadCount,
)
from app.interfaces.api.sse import format_sse, keep_alive

router = APIRouter(tags=["notifications"])

_SSE_RESPONSES = {
    200: {
        "description": "Server-Sent Events stream. Keep-alive `:keep-alive` every ~25 s. "
                       "Use EventSource or curl — Swagger UI cannot display SSE.",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}


@router.get("/notifications", response_class=StreamingResponse, responses=_SSE_RESPONSES)
async def notifications_stream(
    user: AuthenticatedUser = Depends(get_current_user),
    manager: ConnectionManager = Depends(get_connection_manager),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    connection = await manager.connect(user)

    async def events():
        try:
            yield keep_alive()
            while True:
                try:
                    payload = await asyncio.wait_for(
                        connection.queue.get(),
                        timeout=settings.notification_keepalive_seconds,
                    )
                    yield format_sse(payload)
                except asyncio.TimeoutError:
                    yield keep_alive()
        finally:
            await manager.disconnect(connection)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/notifications/history", response_model=NotificationList)
async def notifications_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    unread_only: bool = False,
    user: AuthenticatedUser = Depends(get_current_user),
    repo: NotificationRepository = Depends(get_notification_repo),
) -> NotificationList:
    items = await repo.list_history(
        user_id=user.id,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
    )
    total = await repo.total_for_user(user.id, unread_only=unread_only)
    return NotificationList(
        items=[
            NotificationItem(
                id=item.id,
                event=item.event,
                message=item.message,
                doc_id=item.doc_id,
                is_read=item.is_read,
                created_at=item.created_at,
            )
            for item in items
        ],
        total=total,
    )


@router.get("/notifications/unread-count", response_model=UnreadCount)
async def unread_count(
    user: AuthenticatedUser = Depends(get_current_user),
    repo: NotificationRepository = Depends(get_notification_repo),
) -> UnreadCount:
    return UnreadCount(unread=await repo.unread_count(user.id))


@router.post("/notifications/{notification_id}/read", response_model=NotificationItem)
async def mark_read(
    notification_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    repo: NotificationRepository = Depends(get_notification_repo),
) -> NotificationItem:
    item = await repo.mark_read_for_user(user.id, notification_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return NotificationItem(
        id=item.id,
        event=item.event,
        message=item.message,
        doc_id=item.doc_id,
        is_read=item.is_read,
        created_at=item.created_at,
    )


@router.post(
    "/dev/mock-notifications/doc-new",
    summary="DEV ONLY - simulate notify.doc_new",
    description=(
        "Development-only helper that simulates the Document Service NATS "
        "notify.doc_new event. This does not upload or create a document record."
    ),
)
async def dev_doc_new(
    request: DocNewEventRequest,
    settings: Settings = Depends(get_settings),
    _: AuthenticatedUser = Depends(require_admin),
    service: NotificationService = Depends(get_notification_service),
) -> dict:
    if not settings.enable_dev_endpoints:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    delivered = await service.publish_doc_new(
        DocNewEvent(
            doc_id=request.doc_id,
            document_name=request.document_name,
            classification=request.classification,
            allowed_departments=request.allowed_departments,
            allowed_user_ids=request.allowed_user_ids,
        )
    )
    return {"message": "Mock notification published", "delivered": len(delivered)}
