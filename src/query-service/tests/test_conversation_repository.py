def test_database_url_selects_postgres_conversation_repository(monkeypatch):
    from app.infrastructure.config import get_settings
    from app.infrastructure.db.postgres_conversation_repo import PostgresConversationRepository
    from app.interfaces.api.dependencies import get_conversation_repo

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/query_db")
    get_settings.cache_clear()
    get_conversation_repo.cache_clear()

    assert isinstance(get_conversation_repo(), PostgresConversationRepository)
