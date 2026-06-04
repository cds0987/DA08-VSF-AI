from fastapi import APIRouter, Depends, HTTPException, status

from app.infrastructure.auth.auth_service import AuthenticatedUser
from app.infrastructure.db.mock_conversation_repo import InMemoryConversationRepository
from app.interfaces.api.dependencies import get_conversation_repo, get_current_user
from app.interfaces.api.schemas.query import FeedbackRequest

router = APIRouter(tags=["feedback"])


@router.post("/feedback")
async def feedback(
    request: FeedbackRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    repo: InMemoryConversationRepository = Depends(get_conversation_repo),
) -> dict[str, str]:
    try:
        await repo.save_feedback(request.session_id, request.score)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc
    return {"message": "Feedback recorded"}
