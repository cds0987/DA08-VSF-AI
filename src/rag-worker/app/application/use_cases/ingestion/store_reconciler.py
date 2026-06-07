from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.use_cases.ingestion.ingest_document_use_case import IngestDocumentUseCase
from app.domain.repositories.object_store_lister import ObjectStoreLister
from core_engine.logging_utils import log_event

RAW_PREFIX = "raw/"


@dataclass(frozen=True)
class StoreReconcileSettings:
    enabled: bool = False
    interval_seconds: int = 900
    min_age_seconds: int = 600
    bucket: str = ""


def parse_object_key(key: str) -> tuple[str, str, str] | None:
    if not key.startswith(RAW_PREFIX):
        return None
    rest = key[len(RAW_PREFIX) :]
    doc_id, sep, filename = rest.partition("/")
    if not sep or not doc_id or not filename or "." not in filename:
        return None
    file_type = filename.rsplit(".", 1)[1].lower()
    if not file_type:
        return None
    return doc_id, filename, file_type


async def reconcile_store_once(
    lister: ObjectStoreLister,
    ingest_use_case: IngestDocumentUseCase,
    settings: StoreReconcileSettings,
    logger: logging.Logger,
) -> int:
    scanned = 0
    enqueued = 0
    now = datetime.now(UTC)
    async for obj in lister.list_objects(RAW_PREFIX):
        scanned += 1
        parsed = parse_object_key(obj.key)
        if parsed is None:
            continue
        if (now - obj.last_modified).total_seconds() < settings.min_age_seconds:
            continue
        doc_id, document_name, file_type = parsed
        existing = await ingest_use_case.get_document(doc_id)
        if existing is not None:
            continue
        await ingest_use_case.enqueue(
            document_id=doc_id,
            document_name=document_name,
            file_type=file_type,
            markdown=None,
            source_uri=f"s3://{settings.bucket}/{obj.key}",
            correlation_id=f"reconcile:{doc_id}",
        )
        enqueued += 1
    log_event(
        logger,
        logging.INFO,
        "store_reconcile_completed",
        stage="reconcile",
        scanned=scanned,
        enqueued=enqueued,
        bucket=settings.bucket,
    )
    return enqueued


async def run_store_reconciler(
    lister: ObjectStoreLister,
    ingest_use_case: IngestDocumentUseCase,
    settings: StoreReconcileSettings,
    logger: logging.Logger,
) -> None:
    while True:
        try:
            await reconcile_store_once(lister, ingest_use_case, settings, logger)
        except Exception as exc:  # noqa: BLE001 - maintenance task must keep running
            log_event(
                logger,
                logging.WARNING,
                "store_reconcile_failed",
                stage="reconcile",
                error=str(exc),
            )
        await asyncio.sleep(settings.interval_seconds)
