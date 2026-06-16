#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.auth import AuthSession
from lib.config import parse_args, settings_from_env, validate_settings
from lib.dataset import golden_row, load_questions
from lib.production_client import (
    ProductionClient,
    build_document_map,
    document_id,
    retrieval_rows_from_probe,
    source_doc_ids,
    source_doc_names,
)
from lib.writer import RunWriter, latency_summary, utc_now, write_json, write_report


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = settings_from_env(args)
    validate_settings(settings)
    bundle, questions = load_questions(
        settings.dataset_root,
        settings.dataset,
        limit=settings.limit,
        offset=settings.question_offset,
        include_doc_ids=settings.include_doc_ids,
        exclude_doc_ids=settings.exclude_doc_ids,
        questions_per_doc=settings.questions_per_doc,
    )
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = settings.output_root / f"{run_id}-{settings.dataset}"
    run_dir.mkdir(parents=True, exist_ok=True)
    writer = RunWriter(run_dir)
    writer.touch_outputs()

    manifest = {
        "run_id": run_id,
        "created_at": utc_now(),
        "dataset": settings.dataset,
        "dataset_root": str(bundle.root),
        "golden_path": str(bundle.golden_path),
        "question_count_total": len(bundle.questions),
        "question_count_selected": len(questions),
        "phase_1_5_evidence_targets": [
            "rag_quality",
            "performance",
            "safety_reliability",
            "business_metrics_inputs",
        ],
        "config": settings.public_manifest_config(),
    }
    write_json(run_dir / "manifest.json", manifest)
    for qa in questions:
        await writer.append("golden_qa_used.jsonl", golden_row(qa))

    if settings.dry_run:
        summary = _summary([], auth_refresh_count=0, relogin_count=0)
        write_json(run_dir / "summary.json", summary)
        write_report(run_dir / "report.md", dataset=settings.dataset, summary=summary)
        print(f"Dry run wrote manifest to {run_dir}")
        return 0

    timeout = httpx.Timeout(max(settings.question_timeout_seconds + 15, 45), connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as http_client:
        auth = AuthSession(settings, http_client)
        try:
            await auth.login()
        except httpx.ConnectError as exc:
            raise SystemExit(
                "Could not reach production auth endpoint. Check `PROD_BASE_URL` in "
                "`eval/production-test/.env` and make sure the host resolves from this machine. "
                f"Original error: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise SystemExit(
                "Production auth request failed. Check `PROD_EMAIL`, `PROD_PASSWORD`, gateway auth, "
                f"and base URL. HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        write_json(run_dir / "auth.json", auth.public_auth_info())
        client = ProductionClient(settings, http_client, auth)

        document_lookup: dict[str, dict[str, Any]] = {}
        document_list = await client.list_documents()
        write_json(
            run_dir / "production_documents.json",
            {
                "ok": document_list.get("ok"),
                "error": document_list.get("error"),
                "count": len(document_list.get("documents") or []),
            },
        )
        if document_list.get("ok"):
            document_lookup = build_document_map(document_list.get("documents") or [])

        semaphore = asyncio.Semaphore(settings.concurrency)
        qa_rows: list[dict[str, Any]] = []
        # Enforce minimum interval between request starts to respect server rate limits.
        # Default: 3.5s keeps throughput under 18 req/min (well under common 20 req/min cap).
        # Override via REQUEST_INTERVAL_SECONDS env var.
        request_interval = float(os.getenv("REQUEST_INTERVAL_SECONDS", "3.5"))
        last_sent: list[float] = [0.0]
        throttle_lock = asyncio.Lock()

        async def run_one(index: int, qa: Any) -> None:
            async with semaphore:
                async with throttle_lock:
                    now = asyncio.get_event_loop().time()
                    wait = request_interval - (now - last_sent[0])
                    if wait > 0:
                        await asyncio.sleep(wait)
                    last_sent[0] = asyncio.get_event_loop().time()
                row = await _run_question(
                    index=index,
                    qa=qa,
                    settings=settings,
                    client=client,
                    document_lookup=document_lookup,
                    writer=writer,
                    run_id=run_id,
                )
                qa_rows.append(row)

        await asyncio.gather(*(run_one(index, qa) for index, qa in enumerate(questions, start=1)))

        summary = _summary(
            qa_rows,
            auth_refresh_count=auth.stats.refresh_count,
            relogin_count=auth.stats.relogin_count,
        )
        write_json(run_dir / "summary.json", summary)
        write_report(run_dir / "report.md", dataset=settings.dataset, summary=summary)
        print(f"Production evidence run wrote output to {run_dir}")
        return 1 if summary["failed"] or summary["timed_out"] else 0


async def _run_question(
    *,
    index: int,
    qa: Any,
    settings: Any,
    client: ProductionClient,
    document_lookup: dict[str, dict[str, Any]],
    writer: RunWriter,
    run_id: str,
) -> dict[str, Any]:
    base = {
        **golden_row(qa),
        "run_id": run_id,
        "index": index,
        "started_at": utc_now(),
    }
    trace_session = f"prod-test-{run_id}"
    result = await client.query_with_recovery(
        qa.question,
        trace_session=trace_session,
        conversation_title=f"production-test-{settings.dataset}",
    )
    ended_at = utc_now()

    for event in result.events:
        await writer.append(
            "sse_events.jsonl",
            {
                "run_id": run_id,
                "question_id": qa.question_id,
                **event,
            },
        )

    mapped_document = document_lookup.get(_norm(qa.doc_id)) or document_lookup.get(_norm(Path(qa.doc_id).name))
    mapped_document_id = document_id(mapped_document)
    query_source_ids = source_doc_ids(result.sources)
    probe_ids = [mapped_document_id] if mapped_document_id else query_source_ids
    probe_ids = [doc_id for doc_id in probe_ids if doc_id]
    probe = await client.retrieval_probe(qa.question, probe_ids)
    retrieval_rows = retrieval_rows_from_probe(
        question_id=qa.question_id,
        source_doc=qa.doc_id,
        probe=probe,
        fallback_sources=result.sources,
    )
    for retrieval_row in retrieval_rows:
        await writer.append("retrieval_results.jsonl", retrieval_row)

    done = result.done or {}
    row = {
        **base,
        "ended_at": ended_at,
        "answer": result.answer,
        "status_code": result.status_code,
        "timed_out": result.timed_out,
        "error": result.error,
        "retry_count": result.retry_count,
        "auth_recovered": result.auth_recovered,
        "first_token_latency_seconds": result.first_token_latency_seconds,
        "total_latency_seconds": result.total_latency_seconds,
        "session_id": done.get("session_id"),
        "trace_id": done.get("trace_id"),
        "outcome": done.get("outcome"),
        "outcome_name": _outcome_name(done.get("outcome")),
        "fallback": bool(done.get("fallback")),
        "cached": bool(done.get("cached")),
        "sources": result.sources,
        "source_docs": source_doc_names(result.sources),
        "source_document_ids": query_source_ids,
        "mapped_production_document_id": mapped_document_id,
        "retrieval_probe": {
            "ok": bool(probe.get("ok")),
            "reason": probe.get("reason") or probe.get("error"),
            "requested_document_ids": probe_ids,
            "result_count": len(probe.get("results") or []),
        },
        "retrieved_contexts": retrieval_rows,
    }
    await writer.append("qa_results.jsonl", row)
    return row


def _summary(rows: list[dict[str, Any]], *, auth_refresh_count: int, relogin_count: int) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status_code") == 200 and not row.get("timed_out") and not row.get("error")]
    timed_out = [row for row in rows if row.get("timed_out")]
    failed = [row for row in rows if row not in completed and row not in timed_out]
    retrieval_probe_rows = [row for row in rows if (row.get("retrieval_probe") or {}).get("ok")]
    source_rows = [row for row in rows if row.get("sources")]
    return {
        "total": len(rows),
        "completed": len(completed),
        "timed_out": len(timed_out),
        "failed": len(failed),
        "auth_refresh_count": auth_refresh_count,
        "relogin_count": relogin_count,
        "source_coverage_count": len(source_rows),
        "retrieval_probe_coverage_count": len(retrieval_probe_rows),
        **latency_summary(rows),
    }


def _outcome_name(value: Any) -> str | None:
    try:
        return {
            1: "REFUSE",
            2: "CLARIFY",
            3: "NO_INFO",
            4: "OFF_TOPIC",
            5: "SUCCESS",
            6: "ERROR",
        }.get(int(value), str(value))
    except Exception:  # noqa: BLE001
        return str(value) if value is not None else None


def _norm(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
