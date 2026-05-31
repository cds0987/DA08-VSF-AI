# TODO: AI/Agent Engineer
from app.application.use_cases.query.orchestration import OrchestrationUseCase
from app.infrastructure.db.postgres_conversation_repo import PostgresConversationRepo
from app.infrastructure.external.openai_client import OpenAIClient
from app.infrastructure.external.rag_service_client import RagServiceClient


def get_orchestration_use_case() -> OrchestrationUseCase:
    rag_client = RagServiceClient()
    conversation_repo = PostgresConversationRepo()
    openai_client = OpenAIClient()
    return OrchestrationUseCase(rag_client, conversation_repo, openai_client)
