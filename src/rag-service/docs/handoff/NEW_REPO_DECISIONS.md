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
