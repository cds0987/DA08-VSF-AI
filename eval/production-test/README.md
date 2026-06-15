# Production Evidence Logger

This folder is a black-box production logger for Phase 1.5 evidence. It logs enough raw data for a later evaluator to compute RAG quality, performance, safety/reliability, and business-input metrics. It does not score those metrics itself.

Only files inside `eval/production-test` are needed for this runner.

## Setup

Copy the example env and fill production credentials:

```powershell
Copy-Item eval/production-test/.env.example eval/production-test/.env
notepad eval/production-test/.env
```

Required values:

```env
PROD_BASE_URL=https://your-production-host.example.com
PROD_EMAIL=eval.user@company.com
PROD_PASSWORD=...
```

If your chat UI is under a sub-path such as `https://host/chat` but the APIs are
still served from `https://host/api/*`, the runner will derive the API origin
automatically. You can also override it explicitly:

```env
PROD_BASE_URL=https://host/chat
PROD_API_BASE_URL=https://host
```

If email/password auth on production is unavailable or the account already has a
browser session, you can bootstrap the runner from tokens instead:

```env
PROD_ACCESS_TOKEN=
PROD_REFRESH_TOKEN=
```

`PROD_ACCESS_TOKEN` is tried first. If it is expired, the runner can try
`PROD_REFRESH_TOKEN` and continue from the refreshed session.

Optional MCP values allow the runner to capture real retrieval chunks including `chunk_id` and `parent_text`:

```env
MCP_URL=http://...
MCP_INTERNAL_TOKEN=...
```

Without MCP, `qa_results.jsonl` still contains the public query `sources`, and `retrieval_results.jsonl` falls back to source captions with `probe_ok=false`.

## Commands

Dry run, no production calls:

```powershell
python eval/production-test/run.py --dry-run --limit 3
```

Smoke run:

```powershell
python eval/production-test/run.py --smoke
```

Normal run:

```powershell
python eval/production-test/run.py --dataset dataset_new --limit 30 --concurrency 5
```

Each question has a hard timeout. The default is 30 seconds:

```powershell
python eval/production-test/run.py --question-timeout-seconds 30
```

Evaluate metrics from the latest output run:

```powershell
python eval/production-test/evaluate_metrics.py
```

Evaluate a specific run folder:

```powershell
python eval/production-test/evaluate_metrics.py eval/production-test/output/<run-folder>
```

Metrics config lives in `eval/production-test/.env.metrics`. Add `OPENAI_API_KEY`
there to enable RAGAS LLM judging; without it, the evaluator still writes
fallback diagnostics and marks evidence-dependent metrics as `not_run` when the
run output has no contexts/sources.

## Output

Runs are written to:

```text
eval/production-test/output/<timestamp>-<run-id>-<dataset>/
```

Files:

- `manifest.json`: run config and dataset metadata, secrets redacted.
- `auth.json`: logged-in user id/email/role/department, no tokens.
- `golden_qa_used.jsonl`: selected golden questions.
- `qa_results.jsonl`: question, answer, sources, latency, status, timeout, retry, auth recovery, and retrieval evidence.
- `retrieval_results.jsonl`: one row per probed chunk or source-caption fallback.
- `sse_events.jsonl`: raw JSON-safe SSE events.
- `summary.json`: counts and latency percentiles only.
- `report.md`: compact run summary.

## Later Evaluator Inputs

A later evaluator can compute Phase 1.5 metrics from these fields:

- RAG quality: `question`, `answer`, `golden_answer`, `retrieved_contexts.text`, fallback `sources.caption`.
- Performance: `first_token_latency_seconds`, `total_latency_seconds`, `timed_out`, `error`.
- Safety/reliability: `fallback`, `outcome`, `sources`, `answer`, question metadata.
- Business inputs: answerability from `outcome`, `answer`, and `fallback`.
