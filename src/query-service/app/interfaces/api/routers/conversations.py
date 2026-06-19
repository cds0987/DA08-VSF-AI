from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.ports import AuthenticatedUser
from app.interfaces.api.dependencies import get_conversation_repo, get_current_user
from app.interfaces.api.schemas.conversation import (
    ClearConversationResponse,
    ConversationDetail,
    ConversationList,
    ConversationMessage,
    ConversationMutationResponse,
    ConversationSummary,
    MessageActionStateRequest,
    RenameConversationRequest,
)

router = APIRouter(tags=["conversations"])


@router.get("/conversations", response_model=ConversationList)
async def get_conversations(
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_legacy_messages: bool = Query(default=True),
    user: AuthenticatedUser = Depends(get_current_user),
    repo=Depends(get_conversation_repo),
) -> ConversationList:
    conversations = await repo.list_conversations(user.id, limit=limit, offset=offset)
    legacy_messages = []
    if include_legacy_messages and offset == 0 and conversations:
        legacy_messages = await repo.list_messages(
            user.id,
            conversation_id=conversations[0].id,
            limit=500,
            offset=0,
        )
    return ConversationList(
        conversations=[
            ConversationSummary(
                id=conversation.id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
            for conversation in conversations
        ],
        messages=[
            ConversationMessage(
                id=message.id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                session_id=message.session_id,
                sources=message.sources,
                feedback=message.feedback,
                metadata=getattr(message, "metadata", {}) or {},
            )
            for message in legacy_messages
        ],
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID,
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    repo=Depends(get_conversation_repo),
) -> ConversationDetail:
    conversation = await repo.get_conversation(user.id, str(conversation_id))
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    messages = await repo.list_messages(
        user.id,
        conversation_id=str(conversation_id),
        limit=limit,
        offset=offset,
    )
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            ConversationMessage(
                id=message.id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                session_id=message.session_id,
                sources=message.sources,
                feedback=message.feedback,
                metadata=getattr(message, "metadata", {}) or {},
            )
            for message in messages
        ],
    )


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/actions",
    response_model=ConversationMutationResponse,
)
async def set_message_action_state(
    conversation_id: UUID,
    message_id: UUID,
    request: MessageActionStateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    repo=Depends(get_conversation_repo),
) -> ConversationMutationResponse:
    """Ghi trạng thái thực thi của 1 action (vd đơn nghỉ đã gửi) vào message ->
    bền qua reload/đa thiết bị (xem docs/leave-action-state-b2.md)."""
    update = getattr(repo, "update_message_action", None)
    if update is None:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not supported")
    state = {
        "status": request.status,
        "request_id": request.request_id,
        "leave_status": request.leave_status,
    }
    ok = await update(user.id, str(message_id), request.idempotency_key, state)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return ConversationMutationResponse(message="Action state saved")


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationMutationResponse,
)
async def rename_conversation(
    conversation_id: UUID,
    request: RenameConversationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    repo=Depends(get_conversation_repo),
) -> ConversationMutationResponse:
    renamed = await repo.rename_conversation(
        user.id,
        str(conversation_id),
        request.title.strip(),
    )
    if not renamed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return ConversationMutationResponse(message="Conversation renamed")


@router.delete(
    "/conversations/{conversation_id}",
    response_model=ConversationMutationResponse,
)
async def delete_conversation(
    conversation_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    repo=Depends(get_conversation_repo),
) -> ConversationMutationResponse:
    deleted = await repo.delete_conversation(user.id, str(conversation_id))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return ConversationMutationResponse(message="Conversation deleted")


@router.delete("/conversations", response_model=ClearConversationResponse)
async def clear_conversations(
    user: AuthenticatedUser = Depends(get_current_user),
    repo=Depends(get_conversation_repo),
) -> ClearConversationResponse:
    await repo.clear_history(user.id)
    return ClearConversationResponse(message="Conversation history cleared")
