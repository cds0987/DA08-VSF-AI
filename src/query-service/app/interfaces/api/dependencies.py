from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.ports import AuthenticatedUser
from app.application.langgraph_agent import build_langgraph_agent
from app.application.langgraph_state import create_initial_state
from app.application.intent_classifier import HybridIntentClassifier
from app.application.query_router import QueryRouter
from app.application.use_cases.query.orchestration import QueryOrchestrationUseCase
from app.infrastructure.auth.auth_service import AuthService
from app.infrastructure.cache.rate_limiter import InMemoryRateLimiter, RedisRateLimiter
from app.infrastructure.cache.semantic_cache import InMemorySemanticCache
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db.mock_conversation_repo import InMemoryConversationRepository
from app.infrastructure.db.mock_document_access_repo import InMemoryDocumentAccessRepository
from app.infrastructure.db.mock_notification_repo import InMemoryNotificationRepository
from app.infrastructure.db.mock_user_access_profile_repo import InMemoryUserAccessProfileRepository
from app.infrastructure.db.postgres_conversation_repo import PostgresConversationRepository
from app.infrastructure.db.postgres_document_access_repo import PostgresDocumentAccessRepository
from app.infrastructure.db.postgres_notification_repo import PostgresNotificationRepository
from app.infrastructure.db.postgres_user_access_profile_repo import PostgresUserAccessProfileRepository
from app.infrastructure.external.langchain_mcp_client import LangChainMCPToolsLoader
from app.infrastructure.external.langchain_responses_adapter import OpenAIResponsesChatModel
from app.infrastructure.external.mcp_client import MCPStreamableHttpClient, MockMCPClient
from app.infrastructure.external.intent_ai_client import (
    OpenAIIntentEmbeddingClient,
    OpenAIIntentLLMClient,
    TokenHashIntentEmbeddingClient,
)
from app.infrastructure.external.openai_client import OpenAIStreamingClient
from app.infrastructure.messaging.nats_events import QueryNatsEventHandler
from app.infrastructure.messaging.nats_subscriber import NatsSubscriberManager
from app.infrastructure.messaging.notification_service import NotificationService
from app.infrastructure.guardrails.llm_guard_service import build_guardrails
from app.infrastructure.observability.langfuse_tracing import build_langfuse_callback
from app.infrastructure.sse.connection_manager import ConnectionManager

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    authorization = None
    if credentials:
        authorization = f"{credentials.scheme} {credentials.credentials}"
    user = await AuthService(settings).authenticate(authorization)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    return user


def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


@lru_cache
def get_conversation_repo():
    settings = get_settings()
    if settings.database_url:
        return PostgresConversationRepository(settings.database_url)
    return InMemoryConversationRepository()


@lru_cache
def get_document_access_repo():
    settings = get_settings()
    if settings.nats_mode.strip().lower() == "nats" and settings.database_url:
        return PostgresDocumentAccessRepository(settings.database_url)
    return InMemoryDocumentAccessRepository()


@lru_cache
def get_notification_repo():
    settings = get_settings()
    if settings.nats_mode.strip().lower() == "nats" and settings.database_url:
        return PostgresNotificationRepository(settings.database_url)
    return InMemoryNotificationRepository()


@lru_cache
def get_user_access_profile_repo():
    settings = get_settings()
    if settings.nats_mode.strip().lower() == "nats" and settings.database_url:
        return PostgresUserAccessProfileRepository(settings.database_url)
    return InMemoryUserAccessProfileRepository()


@lru_cache
def get_connection_manager() -> ConnectionManager:
    return ConnectionManager()


@lru_cache
def get_mcp_client():
    settings = get_settings()
    if settings.mcp_mode.strip().lower() in {"real", "mcp"}:
        return MCPStreamableHttpClient(settings)
    return MockMCPClient()


@lru_cache
def get_tool_decision_client():
    return get_query_router()


@lru_cache
def get_intent_embedding_client():
    settings = get_settings()
    if settings.llm_mode.strip().lower() == "openai" and settings.openai_api_key:
        return OpenAIIntentEmbeddingClient(settings)
    return TokenHashIntentEmbeddingClient()


@lru_cache
def get_intent_llm_client():
    settings = get_settings()
    mode = settings.intent_classifier_mode.strip().lower()
    if mode not in {"hybrid", "llm"}:
        return None
    if settings.llm_mode.strip().lower() == "openai" and settings.openai_api_key:
        return OpenAIIntentLLMClient(settings)
    return None


@lru_cache
def get_intent_classifier() -> HybridIntentClassifier:
    return HybridIntentClassifier(
        get_settings(),
        embedding_client=get_intent_embedding_client(),
        llm_client=get_intent_llm_client(),
    )


@lru_cache
def get_query_router() -> QueryRouter:
    return QueryRouter(
        get_settings(),
        get_intent_classifier(),
    )


@lru_cache
def get_semantic_cache() -> InMemorySemanticCache:
    settings = get_settings()
    return InMemorySemanticCache(
        ttl_seconds=settings.semantic_cache_ttl_seconds,
        threshold=settings.semantic_cache_threshold,
    )


@lru_cache
def get_rate_limiter():
    settings = get_settings()
    if (
        settings.rate_limiter_mode.strip().lower() == "redis"
        or settings.app_env.strip().lower() == "production"
    ):
        return RedisRateLimiter(
            redis_url=settings.redis_url,
            max_requests_per_minute=settings.query_rate_limit_per_minute,
        )
    return InMemoryRateLimiter(settings.query_rate_limit_per_minute)


@lru_cache
def get_openai_client() -> OpenAIStreamingClient:
    return OpenAIStreamingClient(get_settings())


@lru_cache
def get_langfuse_callback():
    return build_langfuse_callback(get_settings())


@lru_cache
def get_guardrails():
    return build_guardrails(get_settings())


def get_orchestration_use_case() -> QueryOrchestrationUseCase:
    return QueryOrchestrationUseCase(
        settings=get_settings(),
        conversation_repo=get_conversation_repo(),
        document_access_repo=get_document_access_repo(),
        semantic_cache=get_semantic_cache(),
        mcp_client=get_mcp_client(),
        openai_client=get_openai_client(),
        route_decision_provider=get_query_router(),
        langgraph_agent=get_langgraph_agent(),
        langfuse_callback=get_langfuse_callback(),
        guardrails=get_guardrails(),
    )


def get_notification_service() -> NotificationService:
    return NotificationService(
        repository=get_notification_repo(),
        connection_manager=get_connection_manager(),
    )


@lru_cache
def get_langchain_mcp_tools_loader() -> LangChainMCPToolsLoader | None:
    """
    Build a LangChainMCPToolsLoader when both USE_LANGGRAPH and real MCP are active.
    Returns None for mock mode (think_node falls back to build_langgraph_tools).
    """
    settings = get_settings()
    if not settings.use_langgraph:
        return None
    if settings.mcp_mode.strip().lower() not in {"real", "mcp"}:
        return None
    return LangChainMCPToolsLoader(settings=settings, mcp_client=get_mcp_client())


@lru_cache
def get_langchain_model() -> OpenAIResponsesChatModel:
    """LangChain-compatible model wrapping OpenAI Responses API. Used by LangGraph."""
    settings = get_settings()
    return OpenAIResponsesChatModel(
        api_key=settings.openai_api_key or "",
        model=settings.openai_llm_model,
        timeout=float(settings.openai_timeout_seconds),
    )


@lru_cache
def get_langgraph_agent():
    """
    Cached compiled LangGraph agent. Built once per process.
    Only constructed when use_langgraph=True, otherwise returns None.
    """
    settings = get_settings()
    if not settings.use_langgraph:
        return None
    return build_langgraph_agent(
        model=get_langchain_model(),
        mcp_client=get_mcp_client(),
        tools_loader=get_langchain_mcp_tools_loader(),
    )


@lru_cache
def get_nats_subscriber_manager() -> NatsSubscriberManager | None:
    settings = get_settings()
    if settings.nats_mode.strip().lower() != "nats":
        return None
    handler = QueryNatsEventHandler(
        document_access_repo=get_document_access_repo(),
        notification_service=get_notification_service(),
        user_access_profile_repo=get_user_access_profile_repo(),
        processed_event_max_size=settings.nats_processed_event_max_size,
        processed_event_ttl_seconds=settings.nats_processed_event_ttl_seconds,
    )
    return NatsSubscriberManager(settings, handler)


def reset_state_for_tests() -> None:
    conversation_reset = getattr(get_conversation_repo(), "reset", None)
    if conversation_reset:
        conversation_reset()
    access_reset = getattr(get_document_access_repo(), "reset", None)
    if access_reset:
        access_reset()
    notification_reset = getattr(get_notification_repo(), "reset", None)
    if notification_reset:
        notification_reset()
    get_connection_manager().reset()
    mcp_reset = getattr(get_mcp_client(), "reset", None)
    if mcp_reset:
        mcp_reset()
    get_semantic_cache().reset()
    get_rate_limiter().reset()
    decision_reset = getattr(get_tool_decision_client(), "reset", None)
    if decision_reset:
        decision_reset()
    profile_reset = getattr(get_user_access_profile_repo(), "reset", None)
    if profile_reset:
        profile_reset()
    get_nats_subscriber_manager.cache_clear()
    get_conversation_repo.cache_clear()
    get_document_access_repo.cache_clear()
    get_notification_repo.cache_clear()
    get_user_access_profile_repo.cache_clear()
    get_connection_manager.cache_clear()
    get_mcp_client.cache_clear()
    get_semantic_cache.cache_clear()
    get_rate_limiter.cache_clear()
    get_tool_decision_client.cache_clear()
    get_intent_embedding_client.cache_clear()
    get_intent_llm_client.cache_clear()
    get_intent_classifier.cache_clear()
    get_query_router.cache_clear()
    get_langchain_model.cache_clear()
    get_langchain_mcp_tools_loader.cache_clear()
    get_langgraph_agent.cache_clear()
    get_langfuse_callback.cache_clear()
    get_guardrails.cache_clear()
    get_openai_client.cache_clear()
