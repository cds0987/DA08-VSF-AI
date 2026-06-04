# Validation corpus

Fixture documents in real source formats (`txt`, `md`, `html`, `docx`, `pdf`) used by the
file-ingest end-to-end test [`tests/e2e/test_validation_corpus_ingest_search.py`](../../tests/e2e/test_validation_corpus_ingest_search.py).

Unlike [`tests/e2e/test_inmemory_ingest_search.py`](../../tests/e2e/test_inmemory_ingest_search.py)
— which ingests inline markdown — this corpus exercises the **real `LocalFileParser`** on real
files: text extraction, HTML stripping, docx XML walking, and PDF text-layer reading. The flow is

```
file on disk -> LocalFileParser.parse -> markdown artifact -> engine.ingest -> Qdrant :memory: -> search
```

## Two corpora

| Manifest | Path covered | Suite | Provider |
|---|---|---|---|
| `manifest.json` | text-form parse (`txt/md/html/docx/pdf` text-layer, `pptx/xlsx` via MarkItDown) | always on | offline OK |
| `manifest_ocr.json` | vision OCR (`png/jpg`, scanned PDF, docx with embedded image) | gated | needs real provider |

- **`manifest.json` — text-form, no OCR.** Every file has a real text layer (or extractable
  office text), so the suite stays green offline (no AI gateway / OpenAI key). Driven by
  [`tests/e2e/test_validation_corpus_ingest_search.py`](../../tests/e2e/test_validation_corpus_ingest_search.py).
- **`manifest_ocr.json` — image-only, OCR required.** Each source carries its text *only* inside
  images, so the parser must go through the AI gateway vision path. Driven by
  [`tests/e2e/test_validation_ocr_corpus.py`](../../tests/e2e/test_validation_ocr_corpus.py),
  which **skips unless `RAG_EVAL_REAL_PROVIDER=1`** and a real vision provider is configured
  (see `gap-v2.md` P2 / decision R10).
- Each manifest is the single source of truth: an entry pairs a file with a golden query and the
  document it must retrieve as the top hit. Add a file + entry to extend; both e2es are data-driven
  and need no code change.

## Regenerating binary fixtures

The non-text fixtures (`pptx/xlsx/png/jpg/pdf/docx`) are binary and opaque to review. Regenerate
them from their declared content with:

```
python eval/validation/generate_fixtures.py
```

## Running against a real provider

By default the e2e runs offline (synthetic embeddings + lexical rerank) and proves *plumbing*, not
semantic quality. To validate retrieval quality with a real embedding/rerank provider, set the AI
env and run with `RAG_EVAL_REAL_PROVIDER=1` (the test will then also exercise the real path).

## Files

**`manifest.json` (text-form, offline):**

| File | Format | Topic |
|---|---|---|
| `account_reset.txt` | txt | password reset link expiry |
| `leave_policy.md` | md | annual leave allowance |
| `expense_policy.html` | html | expense reimbursement window |
| `onboarding.docx` | docx | onboarding checklist |
| `security_incident.pdf` | pdf | security incident reporting |
| `remote_work_policy.pptx` | pptx | remote work days per week |
| `travel_per_diem.xlsx` | xlsx | travel per diem meal allowance |

**`manifest_ocr.json` (image-only, gated OCR):**

| File | Format | Topic |
|---|---|---|
| `guest_wifi.png` | png | guest wifi password |
| `visitor_parking.jpg` | jpg | visitor parking location |
| `fire_evacuation_scanned.pdf` | pdf (scanned) | fire evacuation procedure |
| `emergency_contacts.docx` | docx (embedded image) | facilities hotline number |
