from fastapi import APIRouter, Depends, HTTPException, status

from app.application.ports import AuthenticatedUser
from app.interfaces.api.dependencies import get_conversation_repo, get_current_user, get_observability_tracer
from app.interfaces.api.schemas.query import FeedbackRequest

router = APIRouter(tags=["feedback"])


@router.post("/feedback")
async def feedback(
    request: FeedbackRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    repo=Depends(get_conversation_repo),
    tracer=Depends(get_observability_tracer),
) -> dict[str, str]:
    try:
        await repo.save_feedback(request.session_id, request.score)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc
    if tracer is not None and request.trace_id:
        tracer.score(request.trace_id, request.score)
    return {"message": "Feedback recorded"}
