from fastapi import APIRouter, Depends

from app.infrastructure.auth.auth_service import AuthenticatedUser
from app.infrastructure.db.mock_conversation_repo import InMemoryConversationRepository
from app.interfaces.api.dependencies import get_conversation_repo, get_current_user
from app.interfaces.api.schemas.conversation import (
    ClearConversationResponse,
    ConversationHistory,
    ConversationMessage,
)

router = APIRouter(tags=["conversations"])


@router.get("/conversations", response_model=ConversationHistory)
async def get_conversations(
    limit: int = 20,
    offset: int = 0,
    user: AuthenticatedUser = Depends(get_current_user),
    repo: InMemoryConversationRepository = Depends(get_conversation_repo),
) -> ConversationHistory:
    messages = await repo.list_messages(user.id, limit=limit, offset=offset)
    return ConversationHistory(
        messages=[
            ConversationMessage(
                role=message.role,
                content=message.content,
                created_at=message.created_at,
            )
            for message in messages
        ]
    )


@router.delete("/conversations", response_model=ClearConversationResponse)
async def clear_conversations(
    user: AuthenticatedUser = Depends(get_current_user),
    repo: InMemoryConversationRepository = Depends(get_conversation_repo),
) -> ClearConversationResponse:
    await repo.clear_history(user.id)
    return ClearConversationResponse(message="Conversation history cleared")
