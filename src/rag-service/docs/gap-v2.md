# GAP v2 - Production operation review for rag-service

Scope: only `src/rag-service` code and `src/rag-service/docs`.
Grounding docs: `handoff/DAY0_CHECKLIST.md`, `handoff/CONSTRAINTS.md`, `decide/technique/ingestion.md`, `decide/technique/parser.md`, `decide/DATA_LIFECYCLE.md`.
Updated: 2026-06-04

## Summary

The red Day-0 blockers from v2 are now addressed in code:

| Area | Day-0 target | Current state | Level |
|---|---|---|---|
| P1 | Durable ingest pipeline | `POST /api/ingest` enqueues durable `ingest_jobs`, returns `202`, worker loop claims jobs atomically, terminal writes respect `claim_id`, and job status is readable at `GET /api/ingest/jobs/{job_id}` | ✅ |
| P2 | Parse -> canonical artifact -> I/O guard | file-based ingest goes through `Parser`, writes canonical markdown artifact, enforces source allow-list/path traversal/size-before-read, and artifact reads are confined to `ARTIFACT_ROOT` | ✅ |
| P3 | Live readiness, not bootstrap snapshot | `/livez` and `/readyz` are split, readiness recomputes runtime health on each request, and degraded dependencies return `503` | ✅ |
| P4 | Edge guards + explicit auth boundary | request body size and fixed-window rate limit are enforced at the edge; auth boundary is ratified as caller/gateway-owned and service-local auth leftovers are removed | ✅ |
| P5 | Deploy and rollout verification | service-owned Dockerfile, Kubernetes manifests, migration job, rollout verify doc, and CI workflow now live with the service | ✅ |

## What changed

### P1. Durable ingest

- Added `ingest_jobs` domain model, repository contract, SQLAlchemy model, and migration.
- Changed ingest API from inline indexing to `enqueue -> worker claim -> process`.
- Added atomic claim semantics in both repository adapters.
- Guarded terminal job transitions with `claim_id` so stale workers cannot mark a newer claim as completed or failed.
- Added job status endpoint and updated router contract to return `job_id`.

### P2. Parser and artifact flow

- Added `Parser` and `ArtifactStore` contracts.
- Added local implementations with shared source/artifact guards.
- File-based ingest now parses first, writes one canonical markdown artifact, then indexes from that artifact.
- Removed misleading unused parser/observability stubs from the runtime path.

### P3. Live health

- Added `/livez` and `/readyz`.
- Readiness re-probes vector and metadata dependencies at request time.
- Health tests now verify recomputation rather than relying on bootstrap snapshot state.

### P4. Resource guards and trust boundary

- Added request-body size guard and fixed-window rate limit middleware.
- Removed uploader/auth leftovers from the document domain and metadata schema.
- Ratified in docs that rag-service sits behind an authenticated caller boundary; it does not own JWT/authz policy.

### P5. Deploy artifacts

- Added `Dockerfile` for service image build.
- Added Kubernetes config, secret template, migration job, deployment, and service manifests under `deploy/k8s/`.
- Added rollout verification instructions under `deploy/README.md`.
- Added GitHub Actions workflow at `.github/workflows/rag-service-ci.yml` to run tests, migration loop, compile check, and image build.

## Remaining non-red work

The old red blockers are closed, but a few non-blocking items still remain:

- Metrics/tracing and correlation middleware are still not complete enough for the Day-0 observability target.
- Real-provider eval and remote-vector contract checks are still opt-in and not always-on in CI.
- Hybrid retrieval naming/implementation is still behind the search design target.
