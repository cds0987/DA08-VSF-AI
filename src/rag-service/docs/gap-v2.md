# GAP v2 - Production operation review for rag-service

Scope: only `src/rag-service` code and `src/rag-service/docs`.
Grounding docs: `handoff/DAY0_CHECKLIST.md`, `handoff/CONSTRAINTS.md`, `decide/technique/ingestion.md`, `decide/technique/parser.md`, `decide/DATA_LIFECYCLE.md`.
Updated: 2026-06-04

## Summary

The previously reopened Day-0 blockers from the 2026-06-04 second-pass review are now addressed in code:

| Area | Day-0 target | Current state | Level |
|---|---|---|---|
| P1 | Durable ingest pipeline | `POST /api/ingest` enqueues durable `ingest_jobs`, returns `202`, worker loop claims jobs atomically, worker claims are renewed by heartbeat, timed-out `PROCESSING` jobs are reaped to `STALE`, and job status is readable at `GET /api/ingest/jobs/{job_id}` | ✅ |
| P2 | Parse -> canonical artifact -> I/O guard | file-based ingest goes through `Parser`, writes canonical markdown artifact, enforces source allow-list/path traversal/size-before-read, and artifact reads are confined to `ARTIFACT_ROOT` | ✅ |
| P3 | Live readiness, not bootstrap snapshot | `/livez` and `/readyz` are split, readiness recomputes runtime health on each request, and degraded dependencies return `503` | ✅ |
| P4 | Edge guards + explicit auth boundary | request body size and fixed-window rate limit are enforced at the edge; auth boundary is ratified as caller/gateway-owned and service-local auth leftovers are removed | ✅ |
| P5 | Deploy and rollout verification | service-owned Dockerfile, Kubernetes manifests, migration job, rollout verify doc, and CI workflow now live with the service | ✅ |

## What changed

### P1. Durable ingest

- Added `renew_claim()` and `mark_stale_jobs()` to the ingest job repository contract.
- Added worker claim heartbeat renewal while a job is in flight.
- Added a background stale-job reaper that moves timed-out `PROCESSING` jobs back to `STALE`.
- Kept terminal job transitions guarded by `claim_id` so stale workers cannot complete or fail newer claims.

### P2. Parser and artifact flow

- File-based ingest still parses first, writes one canonical markdown artifact, then indexes from that artifact.
- Parser work now runs on a dedicated bounded executor instead of the default shared threadpool.
- Local parser now supports `html`, `docx`, image OCR, scanned PDF OCR, and optional `MarkItDown` conversion for additional Office formats.

### P3. Empty-ingest safety

- `chunk_count == 0` now fails the ingest job instead of marking it `COMPLETED`.
- Scanned PDFs and image files now attempt OCR instead of silently producing an empty ingest result.

### P4. Deploy/runtime support

- Service image now installs `tesseract-ocr` so OCR-backed parser paths are available in production containers.

## Remaining non-red work

The old red blockers are closed, but a few non-blocking items still remain:

- Metrics/tracing and correlation middleware are still not complete enough for the Day-0 observability target.
- Real-provider eval and remote-vector contract checks are still opt-in and not always-on in CI.
- Hybrid retrieval naming/implementation is still behind the search design target.

## Closed gaps from second-pass review

| ID | Resolution |
|---|---|
| G1 | Added lease heartbeat renewal plus stale-job reaping so worker crashes no longer strand jobs in `PROCESSING`. |
| G2 | Moved parser work to a dedicated bounded executor configured by `PARSER_MAX_WORKERS`. |
| G3 | `chunk_count == 0` now fails ingest, and scanned PDFs/images go through OCR instead of silently succeeding empty. |
| G4 | Local parser now handles `html`, `docx`, and OCR image sources directly, with optional `MarkItDown` support for more Office formats. |
