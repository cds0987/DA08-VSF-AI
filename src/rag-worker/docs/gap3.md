# GAP v3 - rag-service: production-readiness follow-up

Scope: only `src/rag-service`.
Grounding docs reviewed before this fix: `docs/gap.md`, `docs/gap-v2.md`, `docs/handoff/CONSTRAINTS.md`, `docs/decide/technique/parser.md`.
Updated: 2026-06-04

## Status

This pass started from a real-code review of `app/`, `core_engine/`, `requirements.txt`, and `deploy/`.

Three actionable gaps from the original v3 note are now closed in code:

| ID | Area | Previous gap | Current state |
|---|---|---|---|
| V3-1 | Metadata DB driver | `requirements.txt` shipped `asyncpg` while deploy/runtime used sync SQLAlchemy with `postgresql+psycopg://` | Closed: runtime now validates PostgreSQL URLs must use `postgresql+psycopg://`, and dependencies ship `psycopg[binary]` |
| V3-2 | Optional Office parser dependency | `LocalFileParser` imported `MarkItDown` but the image did not install it | Closed: dependencies now ship `markitdown[pptx,xls,xlsx]` (narrowed from `[all]`, which pulled an unsatisfiable `youtube-transcript-api~=1.0.0`), and the parser only advertises the Office suffixes we intentionally support through that adapter |
| V3-3 | In-app rate limiter safety | Per-process limiter also throttled `/livez`, `/readyz`, `/health`, and kept empty IP buckets forever | Closed: health routes bypass edge guards, empty buckets are evicted, and body buffering is skipped for bodiless methods |

One note from the original v3 review was stale and is now explicitly corrected here:

- OCR/vision is not local `tesseract` anymore. The current parser renders images/PDF pages and sends them through the AI gateway via `core_engine/ocr`, which matches decision R10 and the parser technique docs.

## What changed

### V3-1. PostgreSQL driver now matches runtime and deploy config

- `PostgresDocumentRepository` is still a sync SQLAlchemy adapter wrapped by `asyncio.to_thread()`.
- `requirements.txt` now ships `psycopg[binary]` instead of `asyncpg`.
- Startup validation now rejects PostgreSQL URLs that do not use `postgresql+psycopg://`, so config drift fails fast instead of surfacing later as an engine import error.

### V3-2. MarkItDown dependency is now real, and support is honest

- `requirements.txt` now includes `markitdown[pptx,xls,xlsx]` (narrowed from `[all]`).
- `LocalFileParser` keeps native handlers for `md`, `txt`, `html`, `docx`, `pdf`, and images.
- The MarkItDown adapter is now only advertised for the suffixes we intentionally support through it: `pptx`, `xls`, `xlsx`.
- Legacy `doc` / `ppt` are no longer claimed by the local parser contract.
- The `[all]` extra was rejected: it pulls `youtube-transcript-api~=1.0.0` (no satisfiable release on PyPI) plus azure/speechrecognition/pandas weight. `markitdown[pptx,xls,xlsx]==0.1.6` resolves cleanly against the pinned `openai==1.59.6` (verified with `pip install --dry-run`).

### V3-3. Health probes are no longer rate-limited

- `/livez`, `/readyz`, and `/health` bypass the in-app edge guard middleware.
- Fixed-window buckets are evicted when they become empty, avoiding unbounded growth by idle IPs.
- The middleware now avoids eagerly buffering request bodies for methods that normally do not carry one.

## Remaining low-risk follow-up

The environment fragility note from the original v3 review still stands as a low-priority operational concern:

- Full local test reliability still depends on using the pinned Python/runtime environment and installing all dependencies before running the entire suite.
- SQLite-based tests are still weaker than a real PostgreSQL contract run for timezone/driver semantics.

## References

- [gap.md](./gap.md)
- [gap-v2.md](./gap-v2.md)
- [parser technique](./decide/technique/parser.md)
- [constraints handoff](./handoff/CONSTRAINTS.md)
