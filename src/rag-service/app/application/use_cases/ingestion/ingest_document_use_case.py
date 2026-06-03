from __future__ import annotations

from haystack_interface.engine import HaystackRagEngine, IngestInput


class IngestDocumentUseCase:
    def __init__(self, engine: HaystackRagEngine):
        self._engine = engine

    async def ingest(
        self,
        *,
        document_id: str,
        document_name: str,
        file_type: str,
        markdown: str,
        source_uri: str | None = None,
        artifact_uri: str | None = None,
    ) -> int:
        return await self._engine.ingest(
            IngestInput(
                document_id=document_id,
                document_name=document_name,
                file_type=file_type,
                markdown=markdown,
                source_uri=source_uri,
                artifact_uri=artifact_uri,
            )
        )

    async def delete(self, document_id: str) -> None:
        await self._engine.vectors.delete_by_document(document_id)
