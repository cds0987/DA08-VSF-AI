# GAP v5 - rag-service: module severability + benchmark harness

Scope: only `src/rag-service`.
Grounding: `docs/gap.md`, `docs/gap-v2.md`, `docs/gap3.md`, `docs/gap4.md`,
`docs/handoff/CONSTRAINTS.md`, `docs/decide/technique/*`.
Updated: 2026-06-04

## Summary

This pass focused on the remaining hardcoded switches that blocked "swap by one env line" experiments.

Those modularity gaps are now closed:

| ID | Area | Previous gap | Current state |
|---|---|---|---|
| V5-4 | Caption toggle via env | Caption on/off required changing `build_engine(caption=...)` in code | Closed: `CAPTION_ENABLED=true|false` is now read by the engine composition root, while explicit function args still override it |
| V5-5 | Reranker selection via env | Factory hardcoded `LLMReranker(provider)` unless a caller injected a custom object | Closed: `RERANK_PROVIDER=llm|lexical|none` now selects the rerank strategy without code edits |

The benchmark instrumentation gaps remain open and are intentionally separate from this hardcode pass:

| ID | Area | Current state | Level |
|---|---|---|---|
| V5-6 | Per-stage timing | Not implemented in production hot paths yet | Red for benchmarking |
| V5-7 | Search latency harness | Only partial eval coverage exists | Medium |
| V5-8 | OCR performance + cost metrics | Not implemented yet | Red for benchmarking |
| V5-9 | Quantitative retrieval metrics | Golden tests still mostly boolean/contract-oriented | Medium |
| V5-10 | Memory harness | Not implemented yet | Red for benchmarking |

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

### Config surface updated

- `.env.example` now documents `CAPTION_ENABLED` and `RERANK_PROVIDER`.
- Tests now cover both env-driven wiring and invalid config values.

## Remaining benchmark work

The repo is now easier to swap for A/B runs, but it still does not measure the outcome deeply enough for performance benchmarking:

1. Add per-stage `duration_ms` in ingest/search/OCR paths.
2. Extend eval harness with per-stage p95 and quantitative metrics like recall@k / MRR / nDCG.
3. Add OCR throughput/cost instrumentation.
4. Add a dedicated memory benchmark script outside production hot paths.

## References

- [gap.md](./gap.md)
- [gap-v2.md](./gap-v2.md)
- [gap3.md](./gap3.md)
- [search technique](./decide/technique/search.md)
- [ingestion technique](./decide/technique/ingestion.md)
- [constraints](./handoff/CONSTRAINTS.md)
