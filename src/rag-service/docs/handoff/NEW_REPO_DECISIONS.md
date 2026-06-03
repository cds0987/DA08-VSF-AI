# NEW_REPO_DECISIONS - Decisions for the production repo

This file records architecture decisions that the current repo has already ratified.

### R1. Retrieval does not enforce access control
**Status:** RATIFIED 2026-06-03 (Codex + user direction)
**Different from prototype:** retrieval no longer accepts user context or filters by ACL.
**Problem:** keep ACL/business logic out of a single-tenant retrieval layer.
**Options considered:**
- A: keep ACL in retrieval - rejected because it mixes concerns and bloats the contract.
- B (chosen): retrieval returns raw unit + lineage; caller filters above.
**Trade-off:** caller must own ACL filtering.
**When to revisit:** if a future multi-tenant contract is intentionally introduced.
**New constraints:** retrieval/search path must not embed role/org-specific logic.

### R2. Search response contract is explicit and citation-ready
**Status:** RATIFIED 2026-06-03 (Codex + user direction)
**Different from prototype:** search results now carry correlation and lineage fields explicitly.
**Problem:** consumers need stable tracing and source citation without reverse-engineering payloads.
**Options considered:**
- A: return a minimal payload - rejected because it breaks the consumer contract.
- B (chosen): return `correlation_id`, `unit_id`, `display_name`, `caption`, `content`, `heading_path`, and `lineage.{source_uri,artifact_uri}`.
**Trade-off:** larger response payload and more mapper code in vector adapters.
**When to revisit:** when the consumer contract versions.
**New constraints:** search responses must always preserve lineage and full content fields.

### R3. Production is fail-closed; degraded mode is visible in health
**Status:** RATIFIED 2026-06-03 (Codex + user direction)
**Different from prototype:** production startup fails if the service would silently run on offline AI or in-process vector storage.
**Problem:** the most dangerous failure mode is "service is up but using the wrong backend".
**Options considered:**
- A: silent automatic fallback everywhere - rejected because it violates fail-closed.
- B (chosen): production raises at startup; dev/test may run degraded but must expose that through `/health`.
**Trade-off:** deployment must provide explicit environment and backend configuration.
**When to revisit:** when an execution-fallback policy is explicitly ratified for a capability.
**New constraints:** production must not start with offline AI or in-process vector storage.

### R4. Re-ingest uses overwrite first, prune stale chunk ids after
**Status:** RATIFIED 2026-06-03 (Codex + user direction)
**Different from prototype:** re-ingest no longer deletes the full document before writing the replacement.
**Problem:** delete-then-recreate creates a data-loss window if the process crashes between the two steps.
**Options considered:**
- A: delete the whole document first - rejected because it recreates the forbidden anti-pattern.
- B (chosen): list current chunk ids, upsert deterministic replacement ids first, then delete only `old_ids - new_ids`.
**Trade-off:** vector providers must support listing chunk ids by document.
**When to revisit:** when metadata/job state is added and the full `mark -> overwrite -> prune -> complete` flow can be implemented.
**New constraints:** document replacement must not use delete-then-recreate.

### R5. Job logs have explicit retention and runtime pruning
**Status:** RATIFIED 2026-06-04 (Codex + user direction)
**Different from prototype:** job/audit logs are no longer "append forever"; retention is explicit and enforced by a background pruner.
**Problem:** unbounded audit rows become dead storage and violate the Day-0 lifecycle requirement.
**Options considered:**
- A: keep logs forever - rejected because it recreates prototype growth/orphan risk.
- B (chosen): keep `job_logs` with explicit retention config and prune them on a runtime schedule.
**Trade-off:** runtime owns one more background maintenance task and retention must be tuned per environment.
**When to revisit:** when lifecycle moves to an external scheduler or metadata backend provides native TTL.
**New constraints:** every storage path must declare owner, retention, and cleanup; `job_logs` default retention is config-driven and must not block ingest.

### R6. Ingest is a durable queued pipeline, not inline HTTP work
**Status:** RATIFIED 2026-06-04 (Codex + user direction)
**Different from prototype:** `POST /api/ingest` now enqueues and returns `202`; background workers claim durable jobs and finish indexing outside the request path.
**Problem:** inline ingest loses work on restart, times out on real files, and races on concurrent re-ingest.
**Options considered:**
- A: keep inline HTTP ingest - rejected because it violates Day-0 queue recovery and atomic-claim constraints.
- B (chosen): store `ingest_jobs`, atomically claim one pending job, and guard terminal transitions with `claim_id`.
**Trade-off:** one more runtime background loop and one more metadata table.
**When to revisit:** when workers move out of process into a dedicated queue system.
**New constraints:** queue state is durable, claim ownership is explicit, and terminal writes must respect `claim_id`.

### R7. Canonical markdown is stored as an artifact before indexing
**Status:** RATIFIED 2026-06-04 (Codex + user direction)
**Different from prototype:** ingest no longer assumes caller-supplied markdown only; file-based ingest passes through a parser and writes a canonical markdown artifact before `engine.ingest`.
**Problem:** replay, reindex, and parse-time guards are impossible if the pipeline indexes ephemeral content directly.
**Options considered:**
- A: index caller payload directly - rejected because it prevents durable replay and weakens I/O guardrails.
- B (chosen): parse to markdown, persist one canonical artifact, and have downstream indexing read that artifact.
**Trade-off:** extra local artifact I/O and retention ownership.
**When to revisit:** when the artifact store moves from local disk to object storage.
**New constraints:** file ingestion must pass size and path guards before read; downstream indexing consumes canonical artifact content, not transient parser output.

### R8. rag-service trusts an authenticated caller boundary
**Status:** RATIFIED 2026-06-04 (Codex + user direction)
**Different from prototype:** rag-service does not carry its own JWT workflow or uploader identity fields.
**Problem:** access control inside the retrieval service conflicts with the documented trust boundary and muddies the service contract.
**Options considered:**
- A: add service-local JWT enforcement - rejected because it contradicts the documented single-tenant/caller-owned boundary.
- B (chosen): remove auth leftovers and treat rag-service as a trusted downstream behind caller or gateway auth.
**Trade-off:** upstream systems must enforce identity and authorization consistently.
**When to revisit:** only if a new multi-tenant contract is explicitly ratified.
**New constraints:** rag-service must not grow local JWT/authz policy by accident; uploader identity is not part of the document domain model.

### R9. Service-owned deploy verification artifacts live with rag-service
**Status:** RATIFIED 2026-06-04 (Codex + user direction)
**Different from prototype:** the service now owns a Dockerfile, Kubernetes manifests, and a CI workflow that runs tests, migration loop, compile check, and image build.
**Problem:** rollout success is not proof that the intended image, schema, and readiness contract are actually live.
**Options considered:**
- A: leave deploy knowledge implicit in project-level infra - rejected because the service then cannot prove its own runtime contract.
- B (chosen): keep service-scoped deploy artifacts and rollout verification steps next to the code.
**Trade-off:** deploy templates must be kept in sync with runtime changes.
**When to revisit:** when platform tooling generates these artifacts from a higher-level source of truth.
**New constraints:** rollout must verify image identity, migration state, and `readyz` after deploy.
