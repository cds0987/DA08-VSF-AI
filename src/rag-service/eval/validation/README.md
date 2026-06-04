# Validation corpus

Fixture documents in real source formats (`txt`, `md`, `html`, `docx`, `pdf`) used by the
file-ingest end-to-end test [`tests/e2e/test_validation_corpus_ingest_search.py`](../../tests/e2e/test_validation_corpus_ingest_search.py).

Unlike [`tests/e2e/test_inmemory_ingest_search.py`](../../tests/e2e/test_inmemory_ingest_search.py)
— which ingests inline markdown — this corpus exercises the **real `LocalFileParser`** on real
files: text extraction, HTML stripping, docx XML walking, and PDF text-layer reading. The flow is

```
file on disk -> LocalFileParser.parse -> markdown artifact -> engine.ingest -> Qdrant :memory: -> search
```

## Constraints

- **Text-form only, no OCR.** Every file has a real text layer, so the suite stays green offline
  (no AI gateway / OpenAI key). Image-only files and scanned PDFs are intentionally excluded —
  they require vision through the AI gateway (see `gap-v2.md` P2 / decision R10).
- `manifest.json` is the single source of truth: each entry pairs a file with a golden query and
  the document it must retrieve as the top hit. Add a file + entry to extend the corpus; the e2e
  is data-driven and needs no code change.

## Running against a real provider

By default the e2e runs offline (synthetic embeddings + lexical rerank) and proves *plumbing*, not
semantic quality. To validate retrieval quality with a real embedding/rerank provider, set the AI
env and run with `RAG_EVAL_REAL_PROVIDER=1` (the test will then also exercise the real path).

## Files

| File | Format | Topic |
|---|---|---|
| `account_reset.txt` | txt | password reset link expiry |
| `leave_policy.md` | md | annual leave allowance |
| `expense_policy.html` | html | expense reimbursement window |
| `onboarding.docx` | docx | onboarding checklist |
| `security_incident.pdf` | pdf | security incident reporting |
