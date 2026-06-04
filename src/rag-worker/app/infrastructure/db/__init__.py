from app.infrastructure.db.inmemory_document_repository import InMemoryDocumentRepository

__all__ = ["InMemoryDocumentRepository", "PostgresDocumentRepository"]


def __getattr__(name: str):
    if name == "PostgresDocumentRepository":
        from app.infrastructure.db.postgres_document_repository import PostgresDocumentRepository

        return PostgresDocumentRepository
    raise AttributeError(name)
