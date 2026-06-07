from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.domain.entities.document import Document, DocumentStatus
from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.infrastructure.db import InMemoryDocumentRepository


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


class ZeroChunkEngine(StubEngine):
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

    async def write_markdown(self, document_id: str, markdown: str) -> str:
        self.writes[document_id] = markdown
        return f"artifact://{document_id}.md"

    async def read_markdown(self, artifact_uri: str) -> str:
        document_id = artifact_uri.removeprefix("artifact://").removesuffix(".md")
        return self.writes[document_id]


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


class EnqueueFailingDocuments(InMemoryDocumentRepository):
    async def enqueue(self, job: IngestJob) -> IngestJob:
        raise RuntimeError("queue down")


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
        assert await use_case.get_document("doc-2") is None
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

    asyncio.run(scenario())
