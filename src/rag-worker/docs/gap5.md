# GAP v5 - rag-service: module severability + benchmark harness

Scope: only `src/rag-service`.
Grounding: `docs/gap.md`, `docs/gap-v2.md`, `docs/gap3.md`, `docs/gap4.md`,
`docs/handoff/CONSTRAINTS.md`, `docs/decide/technique/*`.
Updated: 2026-06-04

## Summary

This pass closed both halves of "test performance by config": the hardcoded switches that
blocked "swap by one env line" experiments, AND the missing instrumentation needed to
actually measure the outcome (time / OCR throughput / retrieval quality / memory).

The modularity gaps are now closed:

| ID | Area | Previous gap | Current state |
|---|---|---|---|
| V5-4 | Caption toggle via env | Caption on/off required changing `build_engine(caption=...)` in code | Closed: `CAPTION_ENABLED=true|false` is now read by the engine composition root, while explicit function args still override it |
| V5-5 | Reranker selection via env | Factory hardcoded `LLMReranker(provider)` unless a caller injected a custom object | Closed: `RERANK_PROVIDER=llm|lexical|none` now selects the rerank strategy without code edits |

The benchmark instrumentation gaps are now closed as well:

| ID | Area | Previous gap | Current state |
|---|---|---|---|
| V5-6 | Per-stage timing | No `duration_ms` in production hot paths | Closed: `engine.py` emits `split_ms`/`caption_ms`/`embed_ms`/`vector_write_ms`/`total_ms` on `ingest_completed` and `embed_ms`/`vector_search_ms`/`rerank_ms`/`total_ms` on `search_completed`, via a shared `Stopwatch` helper |
| V5-7 | Search latency harness | Only e2e p95 in eval, real-provider only | Closed: `scripts/benchmark.py` reports per-stage p50/p95/mean/max from the same logged events under the current env config |
| V5-8 | OCR performance metrics | No metrics around OCR | Closed: `ocr/extractor.py` emits `total_ms`/`avg_page_ms`/`max_page_ms`/`pages_per_second` on `ocr_extracted` (per-page vision timing) |
| V5-9 | Quantitative retrieval metrics | Golden tests boolean/contract-only | Closed: `tests/eval/test_golden_queries.py` adds recall@k / MRR / nDCG with env-tunable thresholds (`RAG_EVAL_MIN_RECALL/MRR/NDCG`) |
| V5-10 | Memory harness | None | Closed: `scripts/benchmark.py` wraps the ingest+search loop in `tracemalloc` and reports current/peak MB |

> $-cost estimation for OCR is intentionally NOT added: it needs per-model pricing
> config and would be guesswork. The harness measures real throughput (`pages_per_second`,
> per-page ms) instead; wire pricing into the cost guardrail work (gap.md #24) when ratified.

## What changed

### V5-4. Caption can now be toggled by config

- `core_engine/factory.py` now reads `CAPTION_ENABLED` when a caller does not pass `caption=...` explicitly.
- Valid values are strict booleans (`1/0`, `true/false`, `yes/no`, `on/off`) so config mistakes fail fast instead of silently drifting behavior.
- `app/interfaces/api/runtime.py` validates this at startup as part of config compatibility checks.

### V5-5. Reranker is no longer hardwired to LLM

- `core_engine/factory.py` now reads `RERANK_PROVIDER`.
- Supported values:
  - `llm`: keep current behavior with `LLMReranker`
  - `lexical`: use `LexicalRerankerService`
  - `none`: use a no-op reranker that preserves vector ranking and skips rerank logic
- Explicit `reranker=` injection still wins over env selection, so tests and custom wiring keep their current escape hatch.

### Per-stage timing (V5-6)

- New `Stopwatch` helper in `core_engine/logging_utils.py` (stdlib `perf_counter`, ms).
- `core_engine/engine.py` times each ingest/search stage and adds the `*_ms` fields to the
  existing `ingest_completed` / `search_completed` structured events — no new log lines, so
  `correlation_id` correlation still holds.

### OCR metrics (V5-8)

- `core_engine/ocr/extractor.py` times each per-page vision call and reports throughput
  (`pages_per_second`) plus `avg_page_ms` / `max_page_ms` on the `ocr_extracted` event.

### Quantitative retrieval metrics (V5-9)

- `tests/eval/test_golden_queries.py` adds `recall_at_k` / `reciprocal_rank` / `ndcg_at_k`
  helpers and a test asserting aggregate recall@k / MRR / nDCG over the golden set.
- Thresholds are env-tunable (`RAG_EVAL_MIN_RECALL`, `RAG_EVAL_MIN_MRR`, `RAG_EVAL_MIN_NDCG`)
  so the same test doubles as an offline plumbing check and a real-provider quality gate.

### Benchmark harness (V5-7, V5-10)

- `scripts/benchmark.py` builds the engine from the CURRENT env (honoring the swap-by-one-line
  design), runs a small golden corpus, and reports: per-stage p50/p95/mean/max (read back from
  the logged events), recall@k, OCR throughput, and `tracemalloc` current/peak memory.
- Output is JSON; `--csv <path>` appends one summary row per run for grid A/B comparisons.
- It adds no service dependency (stdlib only) and runs offline by default.

### Config surface updated

- `.env.example` documents `CAPTION_ENABLED`, `RERANK_PROVIDER` (+ the `none` / threshold note),
  the eval metric thresholds, and the benchmark script.
- Tests cover env-driven wiring, invalid config values, the noop reranker, and the new metrics.

## References

- [gap.md](./gap.md)
- [gap-v2.md](./gap-v2.md)
- [gap3.md](./gap3.md)
- [search technique](./decide/technique/search.md)
- [ingestion technique](./decide/technique/ingestion.md)
- [constraints](./handoff/CONSTRAINTS.md)
