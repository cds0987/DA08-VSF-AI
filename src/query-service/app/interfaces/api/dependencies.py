from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.use_cases.query.orchestration import QueryOrchestrationUseCase
from app.infrastructure.auth.auth_service import AuthService, AuthenticatedUser
from app.infrastructure.cache.rate_limiter import InMemoryRateLimiter
from app.infrastructure.cache.semantic_cache import InMemorySemanticCache
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db.mock_conversation_repo import InMemoryConversationRepository
from app.infrastructure.db.mock_document_access_repo import InMemoryDocumentAccessRepository
from app.infrastructure.db.mock_notification_repo import InMemoryNotificationRepository
from app.infrastructure.external.mcp_client import MockMCPClient
from app.infrastructure.external.openai_client import OpenAIStreamingClient
from app.infrastructure.messaging.notification_service import NotificationService
from app.infrastructure.sse.connection_manager import ConnectionManager

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    authorization = None
    if credentials:
        authorization = f"{credentials.scheme} {credentials.credentials}"
    user = AuthService(settings).authenticate(authorization)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    return user


def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


@lru_cache
def get_conversation_repo() -> InMemoryConversationRepository:
    return InMemoryConversationRepository()


@lru_cache
def get_document_access_repo() -> InMemoryDocumentAccessRepository:
    return InMemoryDocumentAccessRepository()


@lru_cache
def get_notification_repo() -> InMemoryNotificationRepository:
    return InMemoryNotificationRepository()


@lru_cache
def get_connection_manager() -> ConnectionManager:
    return ConnectionManager()


@lru_cache
def get_mcp_client() -> MockMCPClient:
    return MockMCPClient()


@lru_cache
def get_semantic_cache() -> InMemorySemanticCache:
    settings = get_settings()
    return InMemorySemanticCache(
        ttl_seconds=settings.semantic_cache_ttl_seconds,
        threshold=settings.semantic_cache_threshold,
    )


@lru_cache
def get_rate_limiter() -> InMemoryRateLimiter:
    settings = get_settings()
    return InMemoryRateLimiter(settings.query_rate_limit_per_minute)


@lru_cache
def get_openai_client() -> OpenAIStreamingClient:
    return OpenAIStreamingClient(get_settings())


def get_orchestration_use_case() -> QueryOrchestrationUseCase:
    return QueryOrchestrationUseCase(
        settings=get_settings(),
        conversation_repo=get_conversation_repo(),
        document_access_repo=get_document_access_repo(),
        semantic_cache=get_semantic_cache(),
        mcp_client=get_mcp_client(),
        openai_client=get_openai_client(),
    )


def get_notification_service() -> NotificationService:
    return NotificationService(
        repository=get_notification_repo(),
        connection_manager=get_connection_manager(),
    )


def reset_state_for_tests() -> None:
    get_conversation_repo().reset()
    get_document_access_repo().reset()
    get_notification_repo().reset()
    get_connection_manager().reset()
    get_mcp_client().reset()
    get_semantic_cache().reset()
    get_rate_limiter().reset()
