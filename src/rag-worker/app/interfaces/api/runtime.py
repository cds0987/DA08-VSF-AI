from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from fastapi import FastAPI
from sqlalchemy.engine import make_url

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.domain.repositories.artifact_store import ArtifactStore
from app.domain.repositories.document_repository import DocumentRepository
from app.domain.repositories.ingest_job_repository import IngestJobRepository
from app.domain.repositories.parser import Parser
from app.infrastructure.db import InMemoryDocumentRepository
from app.infrastructure.external.local_artifact_store import LocalArtifactStore
from app.infrastructure.external.s3_parser import (
    S3SourceParser,
    collect_storage_startup_diagnostics,
)
from app.interfaces.api.composition import resolve_parser
from core_engine.ai import AISettings, get_ai_provider, load_ai_settings, reset_ai_provider
from core_engine.config import HaystackSettings, load_settings
from core_engine.config_loader import load_config
from core_engine.config_schema import PipelineConfig
from core_engine.factory import (
    build_engine,
    caption_enabled_from_env,
    rerank_provider_from_env,
)
from core_engine.rerank import NoopRerankerService
from core_engine.logging_utils import configure_logging, log_event
from core_engine.mapping import (
    build_ai_provider,
    build_ai_settings,
    build_engine_from_config,
    to_settings,
    to_vector_store_config,
)
from core_engine.ocr import ProviderImageTextExtractor
from core_engine.vectorstore import VectorStoreConfig, available_providers
from core_engine.vectorstore.qdrant_contract import write_contract_stamp


def _is_production(app_env: str) -> bool:
    return app_env.lower() in {"prod", "production"}


@dataclass
class HealthReport:
    status: str
    app_env: str
    ai_provider: str
    vector_provider: str
    vector_deployment: str
    vector_index: str
    metadata_backend: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RuntimeState:
    ingest_use_case: IngestDocumentUseCase | None
    document_repository: DocumentRepository
    job_repository: IngestJobRepository
    parser: Parser
    artifact_store: ArtifactStore
    engine: Any | None
    provider: Any
    vector_config: VectorStoreConfig
    health: HealthReport
    startup_reasons: list[str] = field(default_factory=list)
    source_bucket: str | None = None


@dataclass(frozen=True)
class IngestLeaseSettings:
    stale_timeout_seconds: int = 300
    heartbeat_interval_seconds: float = 30.0
    reaper_interval_seconds: float = 30.0


def load_ingest_lease_settings() -> IngestLeaseSettings:
    raw_timeout = os.getenv("CLAIM_STALE_TIMEOUT_SECONDS") or os.getenv(
        "CLAIM_STALE_TIMEOUT", "300"
    )
    return IngestLeaseSettings(
        stale_timeout_seconds=int(raw_timeout),
        heartbeat_interval_seconds=float(
            os.getenv("CLAIM_HEARTBEAT_INTERVAL_SECONDS", "30")
        ),
        reaper_interval_seconds=float(
            os.getenv("CLAIM_REAPER_INTERVAL_SECONDS", "30")
        ),
    )


@dataclass(frozen=True)
class ParserExecutionSettings:
    max_workers: int = 2


def load_parser_execution_settings() -> ParserExecutionSettings:
    default_workers = max(1, min(4, os.cpu_count() or 1))
    return ParserExecutionSettings(
        max_workers=int(os.getenv("PARSER_MAX_WORKERS", str(default_workers)))
    )


def validate_runtime_settings() -> None:
    settings = load_settings()
    if settings.embed_dimension <= 0:
        raise ValueError("EMBED_DIMENSION must be > 0")
    if settings.top_k_candidates <= 0:
        raise ValueError("SEARCH_TOP_K must be > 0")
    if settings.rerank_top_k <= 0:
        raise ValueError("RERANK_TOP_K must be > 0")
    if settings.top_k_candidates < settings.rerank_top_k:
        raise ValueError("SEARCH_TOP_K must be >= RERANK_TOP_K")
    if not 0.0 <= settings.rerank_threshold <= 1.0:
        raise ValueError("RERANK_THRESHOLD must be between 0 and 1")
    if settings.parent_max_words <= 0:
        raise ValueError("SECTION_MAX_WORDS must be > 0")
    if settings.child_max_words <= 0:
        raise ValueError("CHILD_MAX_WORDS must be > 0")
    if settings.child_overlap_words < 0:
        raise ValueError("CHILD_OVERLAP_WORDS must be >= 0")
    if settings.child_overlap_words >= settings.child_max_words:
        raise ValueError("CHILD_OVERLAP_WORDS must be < CHILD_MAX_WORDS")
    validate_job_log_retention_settings()
    validate_ingest_lease_settings()
    validate_parser_execution_settings()
    caption_enabled_from_env()
    rerank_provider_from_env()
    if int(os.getenv("INGEST_WORKER_COUNT", "1")) <= 0:
        raise ValueError("INGEST_WORKER_COUNT must be > 0")
    if float(os.getenv("INGEST_WORKER_POLL_INTERVAL_SECONDS", "0.5")) <= 0:
        raise ValueError("INGEST_WORKER_POLL_INTERVAL_SECONDS must be > 0")


def validate_vector_config(
    vector_config: VectorStoreConfig,
) -> None:
    if not vector_config.collection.strip():
        raise ValueError("VECTOR_COLLECTION must not be empty")
    if re.search(r"__(?:[a-z0-9-]+__)?d\d+$", vector_config.collection):
        raise ValueError(
            "VECTOR_COLLECTION must not encode model/dimension; index_id() appends __{model_tag}__d{dimension}"
        )
    if vector_config.provider.lower() not in available_providers():
        raise ValueError(
            f"VECTOR_DB_PROVIDER {vector_config.provider!r} is not registered"
        )
    if vector_config.dimension <= 0:
        raise ValueError("Vector store dimension must be > 0")
    if vector_config.deployment == "remote" and not vector_config.url.strip():
        raise ValueError("VECTOR_DB_URL must not be empty for remote vector deployment")
    validate_vector_backend_credentials(vector_config)


def validate_ai_config(ai_settings: AISettings, settings: HaystackSettings) -> None:
    if settings.embed_dimension <= 0:
        raise ValueError("EMBED_DIMENSION must be > 0 for AI embedding")
    for capability_name, capability in (
        ("embed", ai_settings.embed),
        ("caption", ai_settings.caption),
        ("rerank", ai_settings.rerank),
        ("ocr", ai_settings.ocr or ai_settings.caption),
    ):
        if not capability.model.strip():
            raise ValueError(f"AI config for {capability_name} must include a model")


def _is_truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _remote_vector_api_key_required(vector_config: VectorStoreConfig) -> bool:
    explicit = os.getenv("VECTOR_DB_REQUIRE_API_KEY", "")
    if explicit.strip():
        return _is_truthy(explicit)
    if vector_config.deployment != "remote":
        return False
    host = (urlparse(vector_config.url).hostname or "").lower()
    if vector_config.provider.lower() == "qdrant" and "qdrant.io" in host:
        return True
    if vector_config.provider.lower() == "milvus" and "zillizcloud.com" in host:
        return True
    return False


def validate_vector_backend_credentials(vector_config: VectorStoreConfig) -> None:
    if _remote_vector_api_key_required(vector_config) and not vector_config.api_key.strip():
        raise ValueError(
            "VECTOR_DB_API_KEY is required for the configured remote vector backend"
        )


def metadata_backend_name(database_url: str) -> str:
    normalized = database_url.strip()
    if not normalized:
        return "in_memory"
    backend = make_url(normalized).get_backend_name()
    return "postgres" if backend == "postgresql" else backend


def validate_metadata_backend(app_env: str, database_url: str) -> None:
    normalized = database_url.strip()
    if _is_production(app_env) and not normalized:
        raise ValueError(
            "DATABASE_URL must be configured in production; in-memory metadata is not durable"
        )
    if not normalized:
        return
    url = make_url(normalized)
    if (
        url.get_backend_name() == "postgresql"
        and url.drivername != "postgresql+psycopg"
    ):
        raise ValueError(
            "DATABASE_URL must use postgresql+psycopg:// because the metadata repository "
            "uses sync SQLAlchemy with psycopg v3"
        )


@dataclass(frozen=True)
class JobLogRetentionSettings:
    retention_days: int = 30
    prune_interval_seconds: int = 3600


def load_job_log_retention_settings() -> JobLogRetentionSettings:
    return JobLogRetentionSettings(
        retention_days=int(os.getenv("JOBLOG_RETENTION_DAYS", "30")),
        prune_interval_seconds=int(os.getenv("JOBLOG_PRUNE_INTERVAL_SECONDS", "3600")),
    )


def validate_job_log_retention_settings() -> None:
    settings = load_job_log_retention_settings()
    if settings.retention_days <= 0:
        raise ValueError("JOBLOG_RETENTION_DAYS must be > 0")
    if settings.prune_interval_seconds <= 0:
        raise ValueError("JOBLOG_PRUNE_INTERVAL_SECONDS must be > 0")


def validate_ingest_lease_settings() -> None:
    settings = load_ingest_lease_settings()
    if settings.stale_timeout_seconds <= 0:
        raise ValueError("CLAIM_STALE_TIMEOUT_SECONDS must be > 0")
    if settings.heartbeat_interval_seconds <= 0:
        raise ValueError("CLAIM_HEARTBEAT_INTERVAL_SECONDS must be > 0")
    if settings.reaper_interval_seconds <= 0:
        raise ValueError("CLAIM_REAPER_INTERVAL_SECONDS must be > 0")
    if settings.heartbeat_interval_seconds >= settings.stale_timeout_seconds:
        raise ValueError(
            "CLAIM_HEARTBEAT_INTERVAL_SECONDS must be < CLAIM_STALE_TIMEOUT_SECONDS"
        )


def validate_parser_execution_settings() -> None:
    settings = load_parser_execution_settings()
    if settings.max_workers <= 0:
        raise ValueError("PARSER_MAX_WORKERS must be > 0")


async def prune_job_logs_once(
    document_repository: DocumentRepository,
    settings: JobLogRetentionSettings,
    logger: logging.Logger,
) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=settings.retention_days)
    pruned = await document_repository.prune_job_logs_older_than(cutoff)
    log_event(
        logger,
        logging.INFO,
        "job_log_prune_completed",
        stage="retention",
        retention_days=settings.retention_days,
        pruned_count=pruned,
        cutoff=cutoff.isoformat(),
    )
    return pruned


async def run_job_log_pruner(
    document_repository: DocumentRepository,
    settings: JobLogRetentionSettings,
    logger: logging.Logger,
) -> None:
    while True:
        try:
            await prune_job_logs_once(document_repository, settings, logger)
        except Exception as exc:  # noqa: BLE001 - retention is background maintenance
            log_event(
                logger,
                logging.WARNING,
                "job_log_prune_failed",
                stage="retention",
                error=str(exc),
            )
        await asyncio.sleep(settings.prune_interval_seconds)


async def mark_stale_jobs_once(
    job_repository: IngestJobRepository,
    settings: IngestLeaseSettings,
    logger: logging.Logger,
) -> int:
    stale_before = datetime.now(UTC) - timedelta(seconds=settings.stale_timeout_seconds)
    reclaimed = await job_repository.mark_stale_jobs(stale_before)
    if reclaimed:
        log_event(
            logger,
            logging.WARNING,
            "ingest_jobs_marked_stale",
            stage="worker",
            reclaimed_count=reclaimed,
            stale_before=stale_before.isoformat(),
        )
    return reclaimed


async def run_stale_job_reaper(
    job_repository: IngestJobRepository,
    settings: IngestLeaseSettings,
    logger: logging.Logger,
) -> None:
    while True:
        try:
            await mark_stale_jobs_once(job_repository, settings, logger)
        except Exception as exc:  # noqa: BLE001 - recovery must keep running
            log_event(
                logger,
                logging.WARNING,
                "ingest_job_reaper_failed",
                stage="worker",
                error=str(exc),
            )
        await asyncio.sleep(settings.reaper_interval_seconds)


async def run_ingest_worker(
    name: str,
    ingest_use_case: IngestDocumentUseCase,
    poll_interval_seconds: float,
    logger: logging.Logger,
    on_job_finished: Any | None = None,
) -> None:
    while True:
        try:
            job = await ingest_use_case.process_next_job()
            if job is None:
                await asyncio.sleep(poll_interval_seconds)
            else:
                log_event(
                    logger,
                    logging.INFO,
                    "ingest_worker_processed_job",
                    stage="worker",
                    worker=name,
                    job_id=job.id,
                    document_id=job.document_id,
                    status=job.status.value,
                )
                # Publish doc.status qua NATS (no-op nếu không bật NATS).
                if on_job_finished is not None:
                    await on_job_finished(job)
        except Exception as exc:  # noqa: BLE001 - worker must stay alive and keep polling
            log_event(
                logger,
                logging.WARNING,
                "ingest_worker_failed",
                stage="worker",
                worker=name,
                error=str(exc),
            )
            await asyncio.sleep(poll_interval_seconds)


def build_parser(provider: Any) -> Parser:
    # OCR/vision đi qua AI gateway: parser nhận extractor wired từ provider, không
    # tự ôm engine OCR. Composition root là nơi DUY NHẤT nối AI vào parser.
    return resolve_parser(
        "local",
        params={"max_workers": load_parser_execution_settings().max_workers},
        image_text_extractor=ProviderImageTextExtractor(provider),
    )


def build_artifact_store() -> ArtifactStore:
    return LocalArtifactStore()


def _source_bucket() -> str:
    return (
        os.getenv("S3_SOURCE_BUCKET", "").strip()
        or os.getenv("R2_BUCKET", "").strip()
    )


async def compute_health(runtime: RuntimeState) -> HealthReport:
    reasons = list(runtime.startup_reasons)
    if runtime.provider.name == "offline":
        reasons.append("AI provider is offline.")
    if runtime.vector_config.deployment != "remote":
        reasons.append("Vector backend is running in_process.")
    health_metadata_backend = metadata_backend_name(os.getenv("DATABASE_URL", "").strip())
    if health_metadata_backend != "postgres":
        reasons.append(
            f"Document metadata repository is not durable (backend={health_metadata_backend})."
        )
    if runtime.engine is None:
        reasons.append("Engine is not configured.")
    else:
        try:
            await asyncio.wait_for(
                runtime.engine.vectors.list_chunk_ids_by_document("__healthcheck__"),
                timeout=3.0,
            )
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"Vector readiness probe failed: {exc}")
    try:
        await asyncio.wait_for(runtime.document_repository.list_all(limit=1, offset=0), timeout=3.0)
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"Metadata readiness probe failed: {exc}")
    return HealthReport(
        status="healthy" if not reasons else "unhealthy",
        app_env=os.getenv("APP_ENV", "development"),
        ai_provider=runtime.provider.name,
        vector_provider=runtime.vector_config.provider,
        vector_deployment=runtime.vector_config.deployment,
        vector_index=runtime.vector_config.index_id(),
        metadata_backend=metadata_backend_name(os.getenv("DATABASE_URL", "").strip()),
        reasons=reasons,
    )


def bootstrap_runtime() -> RuntimeState:
    configure_logging(logging.getLevelNamesMapping().get(os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
    logger = logging.getLogger(__name__)
    app_env = os.getenv("APP_ENV", "development")
    lease_settings = load_ingest_lease_settings()
    validate_job_log_retention_settings()
    validate_ingest_lease_settings()
    validate_parser_execution_settings()
    caption_enabled_from_env()
    rerank_provider_from_env()
    if int(os.getenv("INGEST_WORKER_COUNT", "1")) <= 0:
        raise ValueError("INGEST_WORKER_COUNT must be > 0")
    if float(os.getenv("INGEST_WORKER_POLL_INTERVAL_SECONDS", "0.5")) <= 0:
        raise ValueError("INGEST_WORKER_POLL_INTERVAL_SECONDS must be > 0")
    database_url = os.getenv("DATABASE_URL", "").strip()
    validate_metadata_backend(app_env, database_url)
    metadata_backend = metadata_backend_name(database_url)
    pipeline_cfg: PipelineConfig | None = None
    pipeline_config_path = Path(os.getenv("PIPELINE_CONFIG", "config.yaml"))

    if pipeline_config_path.is_file():
        pipeline_cfg = load_config(pipeline_config_path)
        if os.getenv("CAPTION_ENABLED", "").strip():
            pipeline_cfg = pipeline_cfg.model_copy(
                update={
                    "captioner": pipeline_cfg.captioner.model_copy(
                        update={"impl": "provider" if caption_enabled_from_env() else "none"}
                    )
                }
            )
        provider = build_ai_provider(pipeline_cfg)
        ai_settings = build_ai_settings(pipeline_cfg)
        settings = to_settings(pipeline_cfg, dim=ai_settings.embed_dimension or provider.dimension)
        validate_ai_config(ai_settings, settings)
        vector_config = to_vector_store_config(
            pipeline_cfg,
            dim=settings.embed_dimension,
        )
        validate_vector_config(vector_config)
    else:
        validate_runtime_settings()
        settings = load_settings()
        ai_settings = load_ai_settings()
        reset_ai_provider()
        provider = get_ai_provider()
        vector_config = VectorStoreConfig.from_env(
            model="offline" if provider.name == "offline" else None,
            dimension=provider.dimension if provider.name == "offline" else settings.embed_dimension,
        )
        settings = HaystackSettings(
            embed_dimension=vector_config.dimension,
            parent_max_words=settings.parent_max_words,
            child_max_words=settings.child_max_words,
            child_overlap_words=settings.child_overlap_words,
            top_k_candidates=settings.top_k_candidates,
            rerank_top_k=settings.rerank_top_k,
            rerank_threshold=settings.rerank_threshold,
        )
        validate_ai_config(ai_settings, settings)
        validate_vector_config(vector_config)

    reasons: list[str] = []
    startup_reasons: list[str] = []
    if provider.name == "offline":
        reasons.append("AI provider is offline.")
    if vector_config.deployment != "remote":
        reasons.append("Vector backend is running in_process.")
    if metadata_backend != "postgres":
        reasons.append(
            f"Document metadata repository is not durable (backend={metadata_backend})."
        )

    if _is_production(app_env) and reasons:
        log_event(
            logger,
            logging.ERROR,
            "runtime_fail_closed",
            stage="startup",
            app_env=app_env,
            reasons=reasons,
            metadata_backend=metadata_backend,
        )
        raise RuntimeError("Production fail-closed: " + " ".join(reasons))

    ingest_use_case = None
    engine = None
    document_repository = build_document_repository()
    if not isinstance(document_repository, IngestJobRepository):
        raise TypeError("document repository must implement IngestJobRepository")
    parser: Parser = build_parser(provider)
    artifact_store = build_artifact_store()
    source_bucket = _source_bucket() or None
    try:
        if pipeline_cfg is not None:
            parser = resolve_parser(
                pipeline_cfg.parser.impl,
                params=pipeline_cfg.parser.params,
                image_text_extractor=ProviderImageTextExtractor(provider),
            )
            # rag-worker = INGEST-ONLY: ép reranker = noop (không search nên không
            # dựng LLM reranker vô ích). Rerank là việc của mcp-service.
            engine = build_engine_from_config(
                pipeline_cfg,
                provider=provider,
                vector_config_override=vector_config,
                reranker_override=NoopRerankerService(),
            )
        else:
            parser = build_parser(provider)
            engine = build_engine(
                provider=provider,
                vector_config=vector_config,
                reranker=NoopRerankerService(),
            )
        vector_config = engine.vectors.config
        ingest_use_case = IngestDocumentUseCase(
            engine,
            document_repository,
            document_repository,
            parser,
            artifact_store,
            claim_heartbeat_interval_seconds=lease_settings.heartbeat_interval_seconds,
        )
        if isinstance(parser, S3SourceParser):
            storage_reasons, storage_warnings = collect_storage_startup_diagnostics(
                source_bucket=source_bucket
            )
            startup_reasons.extend(storage_reasons)
            for warning in storage_warnings:
                log_event(
                    logger,
                    logging.WARNING,
                    "storage_startup_warning",
                    stage="startup",
                    warning=warning,
                    source_bucket=source_bucket or "(none)",
                )
    except Exception as exc:
        startup_reasons.append(f"Engine bootstrap failed: {exc}")
        if _is_production(app_env):
            raise

    reasons.extend(startup_reasons)
    if _is_production(app_env) and startup_reasons:
        log_event(
            logger,
            logging.ERROR,
            "runtime_storage_fail_closed",
            stage="startup",
            app_env=app_env,
            reasons=startup_reasons,
            source_bucket=source_bucket or "(none)",
        )
        raise RuntimeError("Production fail-closed: " + " ".join(startup_reasons))

    health = HealthReport(
        status="healthy" if not reasons else "unhealthy",
        app_env=app_env,
        ai_provider=provider.name,
        vector_provider=vector_config.provider,
        vector_deployment=vector_config.deployment,
        vector_index=vector_config.index_id(),
        metadata_backend=metadata_backend,
        reasons=reasons,
    )
    log_event(
        logger,
        logging.INFO,
        "runtime_bootstrap",
        stage="startup",
        app_env=app_env,
        status=health.status,
        ai_provider=provider.name,
        vector_provider=vector_config.provider,
        vector_deployment=vector_config.deployment,
        vector_index=vector_config.index_id(),
        vector_fingerprint=vector_config.contract().fingerprint,
        metadata_backend=metadata_backend,
    )
    return RuntimeState(
        ingest_use_case=ingest_use_case,
        document_repository=document_repository,
        job_repository=document_repository,
        parser=parser,
        artifact_store=artifact_store,
        engine=engine,
        provider=provider,
        vector_config=vector_config,
        health=health,
        startup_reasons=startup_reasons,
        source_bucket=source_bucket,
    )


def build_document_repository() -> DocumentRepository:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return InMemoryDocumentRepository()
    from app.infrastructure.db import PostgresDocumentRepository

    return PostgresDocumentRepository(database_url)


def _nats_config() -> dict | None:
    """Cấu hình NATS ingest. Không set NATS_URL -> None (không bật NATS)."""
    url = os.getenv("NATS_URL", "").strip()
    if not url:
        return None
    return {
        "url": url,
        "stream": os.getenv("NATS_STREAM", "DOCS"),
        # Mặc định verify-only (fail-closed): stream do DevOps provision trước
        # (infra/nats/jetstream.conf). Dev/CI bật =1 để rag-worker tự dựng stream.
        "auto_create_stream": os.getenv("NATS_STREAM_AUTO_CREATE", "").strip().lower()
        in {"1", "true", "yes", "on"},
        "doc_ingest_subject": os.getenv("NATS_DOC_INGEST_SUBJECT", "doc.ingest"),
        "doc_status_subject": os.getenv("NATS_DOC_STATUS_SUBJECT", "doc.status"),
        # Xóa vector đi qua doc.access{deleted:true} (document-service không gửi
        # doc.delete — không có trong contract infra/nats/subjects.md).
        "doc_access_subject": os.getenv("NATS_DOC_ACCESS_SUBJECT", "doc.access"),
        "durable": os.getenv("NATS_DURABLE", "rag-worker-ingest"),
        "access_durable": os.getenv("NATS_ACCESS_DURABLE", "rag-worker-access"),
        # Bucket ghép vào key trần (raw/<id>/<file>) document-service publish -> s3://bucket/key.
        # Trống -> không ghép (giữ hành vi cũ). Fallback R2_BUCKET cho cấu hình R2.
        "source_bucket": _source_bucket(),
    }


async def start_nats_ingest(
    runtime: "RuntimeState", logger: logging.Logger
) -> tuple[Any, Any, Any, Any]:
    """Bật cửa ingest NATS nếu có NATS_URL.

    Trả (broker, ingest_subscription, access_subscription, status_publisher). Xóa
    vector đi qua doc.access{deleted:true}. Lỗi khi bật NATS -> đóng broker + degrade
    gracefully (trả None): search/HTTP độc lập vẫn chạy, không để NATS hỏng kéo sập
    cả service. Ops theo dõi log ERROR.
    """
    cfg = _nats_config()
    if cfg is None or runtime.ingest_use_case is None:
        return None, None, None, None
    # Lazy import: chưa cài nats-py / không bật NATS thì không kéo dependency.
    from app.infrastructure.external.nats_client import NatsBroker
    from app.interfaces.nats import (
        DocAccessDeleteConsumer,
        DocIngestConsumer,
        DocStatusPublisher,
        start_doc_access_subscription,
        start_doc_ingest_subscription,
    )

    broker = NatsBroker(cfg["url"])
    try:
        await broker.connect()
        # doc.delete KHÔNG nằm trong contract chính thức (infra/nats/subjects.md):
        # xóa vector đi qua doc.access{deleted:true}. Không verify/subscribe doc.delete.
        stream_subjects = [
            cfg["doc_ingest_subject"],
            cfg["doc_status_subject"],
            cfg["doc_access_subject"],
        ]
        if cfg["auto_create_stream"]:
            # Dev/CI: tự dựng stream cho tiện chạy đứng-một-mình.
            await broker.ensure_stream(cfg["stream"], stream_subjects)
        else:
            # Prod mặc định: verify-only fail-closed. Stream phải có sẵn (DevOps
            # provision theo infra/nats/jetstream.conf); thiếu -> raise -> degrade
            # (search/HTTP vẫn chạy) + log ERROR, KHÔNG tự tạo stream lệch chuẩn.
            await broker.verify_stream(cfg["stream"], stream_subjects)
        consumer = DocIngestConsumer(
            runtime.ingest_use_case,
            default_bucket=cfg["source_bucket"] or None,
            logger=logger,
        )
        subscription = await start_doc_ingest_subscription(
            broker,
            consumer,
            subject=cfg["doc_ingest_subject"],
            durable=cfg["durable"],
            logger=logger,
        )
        access_consumer = DocAccessDeleteConsumer(runtime.ingest_use_case, logger=logger)
        access_subscription = await start_doc_access_subscription(
            broker,
            access_consumer,
            subject=cfg["doc_access_subject"],
            durable=cfg["access_durable"],
            logger=logger,
        )
    except Exception as exc:  # noqa: BLE001 - NATS hỏng không được giết search/HTTP
        with contextlib.suppress(Exception):
            await broker.close()
        log_event(
            logger,
            logging.ERROR,
            "nats_ingest_start_failed",
            stage="startup",
            error=str(exc),
        )
        return None, None, None, None
    publisher = DocStatusPublisher(
        broker, subject=cfg["doc_status_subject"], logger=logger
    )
    log_event(
        logger,
        logging.INFO,
        "nats_ingest_started",
        stage="startup",
        stream=cfg["stream"],
        ingest_subject=cfg["doc_ingest_subject"],
        status_subject=cfg["doc_status_subject"],
        access_subject=cfg["doc_access_subject"],
        source_bucket=cfg["source_bucket"] or "(none)",
    )
    return broker, subscription, access_subscription, publisher


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime = bootstrap_runtime()
    logger = logging.getLogger(__name__)
    await write_contract_stamp(runtime.vector_config, written_by="rag-worker")
    log_event(
        logger,
        logging.INFO,
        "vectorstore_contract_stamp_written",
        stage="startup",
        vector_index=runtime.vector_config.index_id(),
        vector_fingerprint=runtime.vector_config.contract().fingerprint,
    )
    retention_settings = load_job_log_retention_settings()
    lease_settings = load_ingest_lease_settings()
    prune_task = asyncio.create_task(
        run_job_log_pruner(runtime.document_repository, retention_settings, logger)
    )
    stale_reaper_task = asyncio.create_task(
        run_stale_job_reaper(runtime.job_repository, lease_settings, logger)
    )
    # Bật cửa ingest NATS (nếu có NATS_URL); status_publisher đẩy doc.status sau xử lý.
    (
        nats_broker,
        nats_subscription,
        nats_access_subscription,
        status_publisher,
    ) = await start_nats_ingest(runtime, logger)
    on_job_finished = (
        status_publisher.publish_for_job if status_publisher is not None else None
    )
    worker_count = int(os.getenv("INGEST_WORKER_COUNT", "1"))
    worker_poll_interval = float(os.getenv("INGEST_WORKER_POLL_INTERVAL_SECONDS", "0.5"))
    if status_publisher is not None and worker_count <= 0:
        # NATS enqueue được nhưng không worker nào xử lý -> không bao giờ publish
        # doc.status. Cảnh báo để cấu hình sai lộ ra thay vì doc kẹt im lặng.
        log_event(
            logger,
            logging.WARNING,
            "nats_ingest_without_worker",
            stage="startup",
            worker_count=worker_count,
        )
    worker_tasks = []
    if runtime.ingest_use_case is not None:
        worker_tasks = [
            asyncio.create_task(
                run_ingest_worker(
                    f"ingest-worker-{index + 1}",
                    runtime.ingest_use_case,
                    worker_poll_interval,
                    logger,
                    on_job_finished,
                )
            )
            for index in range(worker_count)
        ]
    app.state.nats_broker = nats_broker
    app.state.nats_subscription = nats_subscription
    app.state.nats_access_subscription = nats_access_subscription
    app.state.ingest_use_case = runtime.ingest_use_case
    app.state.runtime = runtime
    app.state.health = runtime.health
    app.state.job_log_prune_task = prune_task
    app.state.ingest_job_reaper_task = stale_reaper_task
    app.state.ingest_worker_tasks = worker_tasks
    try:
        yield
    finally:
        prune_task.cancel()
        stale_reaper_task.cancel()
        for task in worker_tasks:
            task.cancel()
        try:
            await prune_task
        except asyncio.CancelledError:
            log_event(
                logger,
                logging.INFO,
                "job_log_prune_stopped",
                stage="retention",
            )
        try:
            await stale_reaper_task
        except asyncio.CancelledError:
            log_event(
                logger,
                logging.INFO,
                "ingest_job_reaper_stopped",
                stage="worker",
            )
        for task in worker_tasks:
            try:
                await task
            except asyncio.CancelledError:
                log_event(
                    logger,
                    logging.INFO,
                    "ingest_worker_stopped",
                    stage="worker",
                )
        if nats_subscription is not None:
            with contextlib.suppress(Exception):
                await nats_subscription.unsubscribe()
        if nats_access_subscription is not None:
            with contextlib.suppress(Exception):
                await nats_access_subscription.unsubscribe()
        if nats_broker is not None:
            with contextlib.suppress(Exception):
                await nats_broker.close()
        close_parser = getattr(runtime.parser, "close", None)
        if close_parser is not None:
            with contextlib.suppress(Exception):
                close_parser()
