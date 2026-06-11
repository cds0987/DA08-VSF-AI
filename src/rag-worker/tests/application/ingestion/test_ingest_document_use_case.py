from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from qdrant_client.http.exceptions import UnexpectedResponse

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.application.use_cases.ingestion.ingest_document_use_case import classify_ingest_error
from app.domain.entities.document import Document, DocumentStatus
from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.infrastructure.db import InMemoryDocumentRepository
from core_engine.ai import TransientAIError
from core_engine.engine import ChunkLimitExceededError


class StubVectors:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_by_document(self, document_id: str) -> None:
        self.deleted.append(document_id)


class StubEngine:
    def __init__(self) -> None:
        self.ingest_calls = []
        self.vectors = StubVectors()

    async def ingest(self, payload):
        self.ingest_calls.append(payload)
        return 3


class FailingEngine(StubEngine):
    async def ingest(self, payload):
        raise RuntimeError("embed failed")


class TransientFailingEngine(StubEngine):
    async def ingest(self, payload):
        raise TransientAIError("rate limited")


class ZeroChunkEngine(StubEngine):
    async def ingest(self, payload):
        self.ingest_calls.append(payload)
        return 0


class EmptyMarkdownEngine(StubEngine):
    async def ingest(self, payload):
        self.ingest_calls.append(payload)
        return 0 if not payload.markdown.strip() else 1


class RecordingZeroChunkEngine(StubEngine):
    async def ingest(self, payload):
        self.ingest_calls.append(payload)
        return 0


class SlowEngine(StubEngine):
    async def ingest(self, payload):
        self.ingest_calls.append(payload)
        await asyncio.sleep(0.03)
        return 1


class DeletingEngine(StubEngine):
    def __init__(self, documents: InMemoryDocumentRepository) -> None:
        super().__init__()
        self._documents = documents

    async def ingest(self, payload):
        self.ingest_calls.append(payload)
        await self._documents.delete(payload.document_id)
        return 1


class TombstoningEngine(StubEngine):
    def __init__(self, documents: InMemoryDocumentRepository) -> None:
        super().__init__()
        self._documents = documents

    async def ingest(self, payload):
        self.ingest_calls.append(payload)
        await self._documents.update_status(payload.document_id, DocumentStatus.DELETED)
        return 1


class StubParser:
    def __init__(self) -> None:
        self.calls = []

    async def parse(self, *, document_id: str, file_type: str, source_uri: str):
        self.calls.append(
            {
                "document_id": document_id,
                "file_type": file_type,
                "source_uri": source_uri,
            }
        )
        return type(
            "ParsedArtifact",
            (),
            {
                "markdown": "# Parsed\nBody",
                "source_uri": source_uri,
            },
        )()


class StubArtifactStore:
    def __init__(self) -> None:
        self.writes = {}
        self.deleted: list[str] = []

    async def write_markdown(self, document_id: str, markdown: str) -> str:
        self.writes[document_id] = markdown
        return f"artifact://{document_id}.md"

    async def read_markdown(self, artifact_uri: str) -> str:
        document_id = artifact_uri.removeprefix("artifact://").removesuffix(".md")
        return self.writes[document_id]

    async def delete_by_document(self, document_id: str) -> None:
        self.deleted.append(document_id)
        self.writes.pop(document_id, None)


class LogFailingDocuments(InMemoryDocumentRepository):
    async def append_job_log(self, entry):
        raise RuntimeError("job log store down")


class StaleClaimDocuments(InMemoryDocumentRepository):
    def __init__(self, claimed_job: IngestJob) -> None:
        super().__init__()
        self._claimed_job = claimed_job
        self._jobs[claimed_job.id] = claimed_job

    async def claim_next_pending(self, claim_id: str) -> IngestJob | None:
        job = self._claimed_job
        self._claimed_job = IngestJob(
            id=job.id,
            document_id=job.document_id,
            document_name=job.document_name,
            file_type=job.file_type,
            source_uri=job.source_uri,
            markdown=job.markdown,
            artifact_uri=job.artifact_uri,
            correlation_id=job.correlation_id,
            status=IngestJobStatus.PROCESSING,
            claim_id=claim_id,
            attempt=job.attempt + 1,
            chunk_count=job.chunk_count,
            error_message=None,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
        self._jobs[job.id] = self._claimed_job
        return self._claimed_job

    async def complete_job(
        self,
        job_id: str,
        claim_id: str,
        *,
        chunk_count: int,
    ) -> bool:
        return False


class HeartbeatTrackingDocuments(InMemoryDocumentRepository):
    def __init__(self) -> None:
        super().__init__()
        self.renew_calls = 0

    async def renew_claim(self, job_id: str, claim_id: str) -> bool:
        self.renew_calls += 1
        return await super().renew_claim(job_id, claim_id)


class LeaseLosingDocuments(HeartbeatTrackingDocuments):
    async def renew_claim(self, job_id: str, claim_id: str) -> bool:
        self.renew_calls += 1
        return False


class EnqueueFailingDocuments(InMemoryDocumentRepository):
    async def enqueue(self, job: IngestJob) -> IngestJob:
        raise RuntimeError("queue down")


class ExplodingTracer:
    def start_job(self, *args, **kwargs):
        raise RuntimeError("trace start down")

    def span_start(self, *args, **kwargs):
        raise RuntimeError("span start down")

    def span_ok(self, *args, **kwargs):
        raise RuntimeError("span ok down")

    def span_error(self, *args, **kwargs):
        raise RuntimeError("span error down")

    def generation(self, *args, **kwargs):
        raise RuntimeError("generation down")

    async def finish_job(self, *args, **kwargs):
        raise RuntimeError("trace finish down")


def test_ingest_use_case_enqueues_and_processes_markdown_job() -> None:
    async def scenario() -> None:
        engine = StubEngine()
        documents = InMemoryDocumentRepository()
        parser = StubParser()
        artifact_store = StubArtifactStore()
        use_case = IngestDocumentUseCase(engine, documents, documents, parser, artifact_store)

        queued_job = await use_case.enqueue(
            document_id="doc-1",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
            source_uri="local://doc-1.md",
            correlation_id="cid-ingest-1",
        )

        assert queued_job.status is IngestJobStatus.PENDING
        stored_before = await use_case.get_document("doc-1")
        assert stored_before is not None
        assert stored_before.status.value == "queued"

        processed_job = await use_case.process_next_job()

        assert processed_job is not None
        assert processed_job.status is IngestJobStatus.COMPLETED
        assert processed_job.chunk_count == 3
        ingest_input = engine.ingest_calls[0]
        assert ingest_input.document_id == "doc-1"
        assert ingest_input.source_uri == "local://doc-1.md"
        assert ingest_input.artifact_uri == "artifact://doc-1.md"
        stored_after = await use_case.get_document("doc-1")
        assert stored_after is not None
        assert stored_after.status.value == "completed"
        assert stored_after.chunk_count == 3
        logs = await documents.list_job_logs("doc-1")
        assert [entry.status for entry in logs] == ["completed", "processing", "pending"]
        assert all(entry.correlation_id == "cid-ingest-1" for entry in logs)

    asyncio.run(scenario())


def test_ingest_use_case_parses_file_source_before_ingest() -> None:
    async def scenario() -> None:
        engine = StubEngine()
        documents = InMemoryDocumentRepository()
        parser = StubParser()
        artifact_store = StubArtifactStore()
        use_case = IngestDocumentUseCase(engine, documents, documents, parser, artifact_store)

        await use_case.enqueue(
            document_id="doc-parse",
            document_name="Guide",
            file_type="pdf",
            markdown=None,
            source_uri="local://doc-parse.pdf",
        )
        await use_case.process_next_job()

        assert parser.calls == [
            {
                "document_id": "doc-parse",
                "file_type": "pdf",
                "source_uri": "local://doc-parse.pdf",
            }
        ]
        assert engine.ingest_calls[0].markdown == "# Parsed\nBody"

    asyncio.run(scenario())


def test_ingest_use_case_deletes_document_vectors() -> None:
    async def scenario() -> None:
        engine = StubEngine()
        documents = InMemoryDocumentRepository()
        parser = StubParser()
        artifact_store = StubArtifactStore()
        use_case = IngestDocumentUseCase(engine, documents, documents, parser, artifact_store)

        await use_case.enqueue(
            document_id="doc-2",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
        )

        await use_case.delete("doc-2")

        assert engine.vectors.deleted == ["doc-2"]
        assert artifact_store.deleted == ["doc-2"]
        deleted = await use_case.get_document("doc-2")
        assert deleted is not None
        assert deleted.status is DocumentStatus.DELETED
        assert await use_case.list_documents() == []
        assert len(documents._jobs) == 0
        assert documents._job_logs == []

    asyncio.run(scenario())


def test_ingest_use_case_logs_failed_runs() -> None:
    async def scenario() -> None:
        engine = FailingEngine()
        documents = InMemoryDocumentRepository()
        parser = StubParser()
        artifact_store = StubArtifactStore()
        use_case = IngestDocumentUseCase(engine, documents, documents, parser, artifact_store)

        await use_case.enqueue(
            document_id="doc-fail",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
        )
        # process_next_job KHÔNG raise nữa: trả job FAILED (để worker publish doc.status:failed).
        processed = await use_case.process_next_job()
        assert processed is not None
        assert processed.status is IngestJobStatus.FAILED
        assert processed.error_message and "embed failed" in processed.error_message

        stored = await use_case.get_document("doc-fail")
        assert stored is not None
        assert stored.status.value == "failed"
        logs = await documents.list_job_logs("doc-fail")
        assert [entry.status for entry in logs] == ["failed", "processing", "pending"]
        assert logs[0].error_type == "RuntimeError"
        job = await use_case.get_job(next(iter(documents._jobs)))
        assert job is not None
        assert job.status is IngestJobStatus.FAILED

    asyncio.run(scenario())


def test_ingest_use_case_fails_when_ingest_produces_zero_chunks() -> None:
    async def scenario() -> None:
        engine = ZeroChunkEngine()
        documents = InMemoryDocumentRepository()
        parser = StubParser()
        artifact_store = StubArtifactStore()
        use_case = IngestDocumentUseCase(engine, documents, documents, parser, artifact_store)

        await use_case.enqueue(
            document_id="doc-empty",
            document_name="Scanned",
            file_type="pdf",
            markdown="# Empty",
        )
        processed = await use_case.process_next_job()
        assert processed is not None
        assert processed.status is IngestJobStatus.FAILED
        assert processed.error_message and "0 chunks" in processed.error_message

        stored = await use_case.get_document("doc-empty")
        assert stored is not None
        assert stored.status is DocumentStatus.FAILED
        job = await use_case.get_job(next(iter(documents._jobs)))
        assert job is not None
        assert job.status is IngestJobStatus.FAILED

    asyncio.run(scenario())


def test_ingest_use_case_passes_empty_markdown_from_empty_csv_source_and_fails_loudly(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        engine = RecordingZeroChunkEngine()
        documents = InMemoryDocumentRepository()
        artifact_store = StubArtifactStore()
        source_root = tmp_path / "sources"
        source_root.mkdir()
        (source_root / "empty.csv").write_text("", encoding="utf-8")
        monkeypatch.setenv("SOURCE_ROOT", str(source_root))
        from app.infrastructure.external.local_parser import LocalFileParser

        real_parser = LocalFileParser(max_workers=1)
        use_case = IngestDocumentUseCase(engine, documents, documents, real_parser, artifact_store)
        try:
            await use_case.enqueue(
                document_id="doc-empty-csv",
                document_name="Empty CSV",
                file_type="csv",
                markdown=None,
                source_uri="local://empty.csv",
            )
            processed = await use_case.process_next_job()
        finally:
            real_parser.close()

        assert processed is not None
        assert processed.status is IngestJobStatus.FAILED
        assert processed.error_message and "0 chunks" in processed.error_message
        assert engine.ingest_calls[0].markdown == ""

    asyncio.run(scenario())


def test_ingest_use_case_does_not_fail_when_job_log_append_fails() -> None:
    async def scenario() -> None:
        engine = StubEngine()
        documents = LogFailingDocuments()
        parser = StubParser()
        artifact_store = StubArtifactStore()
        use_case = IngestDocumentUseCase(engine, documents, documents, parser, artifact_store)

        await use_case.enqueue(
            document_id="doc-log-fail",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
        )
        processed = await use_case.process_next_job()

        assert processed is not None
        stored = await use_case.get_document("doc-log-fail")
        assert stored is not None
        assert stored.status.value == "completed"

    asyncio.run(scenario())


def test_ingest_use_case_renews_claim_while_job_is_running() -> None:
    async def scenario() -> None:
        engine = SlowEngine()
        documents = HeartbeatTrackingDocuments()
        parser = StubParser()
        artifact_store = StubArtifactStore()
        use_case = IngestDocumentUseCase(
            engine,
            documents,
            documents,
            parser,
            artifact_store,
            claim_heartbeat_interval_seconds=0.01,
        )

        await use_case.enqueue(
            document_id="doc-heartbeat",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
        )

        processed = await use_case.process_next_job()

        assert processed is not None
        assert processed.status is IngestJobStatus.COMPLETED
        assert documents.renew_calls >= 1

    asyncio.run(scenario())


def test_ingest_use_case_does_not_overwrite_document_when_claim_is_stale() -> None:
    async def scenario() -> None:
        engine = StubEngine()
        parser = StubParser()
        artifact_store = StubArtifactStore()
        now = datetime.now(UTC)
        documents = StaleClaimDocuments(
            IngestJob(
                id="job-stale",
                document_id="doc-stale",
                document_name="Guide",
                file_type="md",
                source_uri=None,
                markdown="# Title\nBody",
                artifact_uri=None,
                correlation_id="cid-stale",
                status=IngestJobStatus.PENDING,
                created_at=now,
                updated_at=now,
            )
        )
        use_case = IngestDocumentUseCase(engine, documents, documents, parser, artifact_store)
        documents._documents["doc-stale"] = Document(
            id="doc-stale",
            name="Guide",
            file_type="md",
            s3_key="inline://doc-stale",
            status=DocumentStatus.PROCESSING,
            created_at=now,
            chunk_count=7,
            error_message=None,
        )

        processed = await use_case.process_next_job()

        assert processed is not None
        assert processed.status is IngestJobStatus.PROCESSING
        stored = await use_case.get_document("doc-stale")
        assert stored is not None
        assert stored.status.value == "processing"
        assert stored.chunk_count == 7

    asyncio.run(scenario())


def test_enqueue_dedups_redelivered_document() -> None:
    # NATS at-least-once: doc.ingest gửi lại -> enqueue lần 2 KHÔNG tạo job mới.
    async def scenario() -> None:
        documents = InMemoryDocumentRepository()
        use_case = IngestDocumentUseCase(
            StubEngine(), documents, documents, StubParser(), StubArtifactStore()
        )

        first = await use_case.enqueue(
            document_id="doc-dup", document_name="D", file_type="md", markdown="# A"
        )
        second = await use_case.enqueue(
            document_id="doc-dup", document_name="D", file_type="md", markdown="# A"
        )

        assert second.id == first.id  # trả lại job đang chờ, không tạo mới
        active = [j for j in documents._jobs.values() if j.document_id == "doc-dup"]
        assert len(active) == 1

    asyncio.run(scenario())


def test_ingest_use_case_cancels_when_lease_is_lost() -> None:
    async def scenario() -> None:
        engine = SlowEngine()
        documents = LeaseLosingDocuments()
        use_case = IngestDocumentUseCase(
            engine,
            documents,
            documents,
            StubParser(),
            StubArtifactStore(),
            claim_heartbeat_interval_seconds=0.01,
        )

        await use_case.enqueue(
            document_id="doc-lease-lost",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
        )
        processed = await use_case.process_next_job()

        assert processed is not None
        assert processed.status is IngestJobStatus.PROCESSING
        assert documents.renew_calls >= 1

    asyncio.run(scenario())


def test_ingest_use_case_marks_transient_failures_for_reconcile() -> None:
    async def scenario() -> None:
        engine = TransientFailingEngine()
        documents = InMemoryDocumentRepository()
        use_case = IngestDocumentUseCase(
            engine, documents, documents, StubParser(), StubArtifactStore()
        )

        await use_case.enqueue(
            document_id="doc-transient",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
        )
        processed = await use_case.process_next_job()

        assert processed is not None
        assert processed.status is IngestJobStatus.FAILED
        assert processed.error_class == "transient"

    asyncio.run(scenario())


def test_enqueue_skips_completed_document_redelivery() -> None:
    async def scenario() -> None:
        documents = InMemoryDocumentRepository()
        use_case = IngestDocumentUseCase(
            StubEngine(), documents, documents, StubParser(), StubArtifactStore()
        )

        await documents.create(
            Document(
                id="doc-done",
                name="Done",
                file_type="md",
                s3_key="inline://doc-done",
                status=DocumentStatus.COMPLETED,
                created_at=datetime.now(UTC),
                chunk_count=4,
            )
        )

        job = await use_case.enqueue(
            document_id="doc-done", document_name="Done", file_type="md", markdown="# A"
        )

        assert job.status is IngestJobStatus.COMPLETED
        assert documents._jobs == {}

    asyncio.run(scenario())


def test_enqueue_cleans_up_document_when_job_enqueue_fails() -> None:
    async def scenario() -> None:
        documents = EnqueueFailingDocuments()
        use_case = IngestDocumentUseCase(
            StubEngine(), documents, documents, StubParser(), StubArtifactStore()
        )

        with pytest.raises(RuntimeError, match="queue down"):
            await use_case.enqueue(
                document_id="doc-fail-enqueue",
                document_name="D",
                file_type="md",
                markdown="# A",
            )

        assert await use_case.get_document("doc-fail-enqueue") is None

    asyncio.run(scenario())


def test_ingest_use_case_times_out_long_running_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        monkeypatch.setenv("INGEST_JOB_TIMEOUT_SECONDS", "0.01")
        engine = SlowEngine()
        documents = InMemoryDocumentRepository()
        use_case = IngestDocumentUseCase(
            engine, documents, documents, StubParser(), StubArtifactStore()
        )

        await use_case.enqueue(
            document_id="doc-timeout",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
        )
        processed = await use_case.process_next_job()

        assert processed is not None
        assert processed.status is IngestJobStatus.FAILED
        assert "TimeoutError" in (await documents.list_job_logs("doc-timeout"))[0].error_type

    asyncio.run(scenario())


def test_ingest_use_case_cleans_up_vectors_when_document_deleted_mid_ingest() -> None:
    async def scenario() -> None:
        documents = InMemoryDocumentRepository()
        engine = DeletingEngine(documents)
        use_case = IngestDocumentUseCase(
            engine, documents, documents, StubParser(), StubArtifactStore()
        )

        await use_case.enqueue(
            document_id="doc-delete-race",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
        )
        processed = await use_case.process_next_job()

        assert processed is None
        assert engine.vectors.deleted == ["doc-delete-race"]
        assert documents._jobs == {}
        tombstone = await use_case.get_document("doc-delete-race")
        assert tombstone is not None
        assert tombstone.status is DocumentStatus.DELETED

    asyncio.run(scenario())


def test_ingest_use_case_survives_tracer_failures() -> None:
    async def scenario() -> None:
        engine = StubEngine()
        documents = InMemoryDocumentRepository()
        parser = StubParser()
        artifact_store = StubArtifactStore()
        use_case = IngestDocumentUseCase(
            engine,
            documents,
            documents,
            parser,
            artifact_store,
            tracer=ExplodingTracer(),
        )

        await use_case.enqueue(
            document_id="doc-trace-survive",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
        )
        processed = await use_case.process_next_job()

        assert processed is not None
        assert processed.status is IngestJobStatus.COMPLETED

    asyncio.run(scenario())


def test_ingest_use_case_marks_deleted_race_job_as_already_published() -> None:
    async def scenario() -> None:
        documents = InMemoryDocumentRepository()
        engine = TombstoningEngine(documents)
        use_case = IngestDocumentUseCase(
            engine, documents, documents, StubParser(), StubArtifactStore()
        )

        await use_case.enqueue(
            document_id="doc-delete-tombstone",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
        )
        processed = await use_case.process_next_job()

        assert processed is not None
        assert processed.status is IngestJobStatus.FAILED
        assert processed.error_message == "document deleted during ingest"
        assert processed.status_published_at is not None
        pending = await documents.list_pending_status_publications(10)
        assert pending == []

    asyncio.run(scenario())


def test_enqueue_skips_deleted_document() -> None:
    async def scenario() -> None:
        documents = InMemoryDocumentRepository()
        use_case = IngestDocumentUseCase(
            StubEngine(), documents, documents, StubParser(), StubArtifactStore()
        )
        await documents.create(
            Document(
                id="doc-gone",
                name="Gone",
                file_type="md",
                s3_key="inline://doc-gone",
                status=DocumentStatus.DELETED,
                created_at=datetime.now(UTC),
            )
        )

        job = await use_case.enqueue(
            document_id="doc-gone",
            document_name="Gone",
            file_type="md",
            markdown="# A",
        )

        assert job.status is IngestJobStatus.FAILED
        assert job.error_message == "document deleted"
        assert documents._jobs == {}

    asyncio.run(scenario())


def test_inmemory_repository_does_not_revive_deleted_document_status() -> None:
    async def scenario() -> None:
        documents = InMemoryDocumentRepository()
        await documents.create(
            Document(
                id="doc-gone",
                name="Gone",
                file_type="md",
                s3_key="inline://doc-gone",
                status=DocumentStatus.DELETED,
                created_at=datetime.now(UTC),
            )
        )

        await documents.update_status("doc-gone", DocumentStatus.PROCESSING)

        stored = await documents.get_by_id("doc-gone")
        assert stored is not None
        assert stored.status is DocumentStatus.DELETED

    asyncio.run(scenario())


def test_classify_ingest_error_distinguishes_transient_and_permanent() -> None:
    assert classify_ingest_error(TransientAIError("retry")) == "transient"
    assert (
        classify_ingest_error(
            UnexpectedResponse(
                status_code=404,
                reason_phrase="Not Found",
                content="Collection `rag_chatbot__offline__d256` doesn't exist!",
                headers={},
            )
        )
        == "transient"
    )
    assert classify_ingest_error(ChunkLimitExceededError("too many")) == "permanent"
