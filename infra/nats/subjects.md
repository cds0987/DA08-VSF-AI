# NATS Subject Contract

Owner: Backend Dev - Vu Quang Dung.

This file is the source of truth for NATS subjects, payload shape, delivery mode, retry behavior, and idempotency across Document Service, RAG Worker, Query Service, MCP Service, and DevOps.

## Change Rules

- Backend Dev owns subject names, payload versions, stream placement, and delivery semantics.
- Any subject rename, payload field removal/rename, delivery change, or timeout change must be announced to Backend Dev and all producers/consumers before implementation.
- Additive fields are allowed only when consumers can ignore unknown fields.
- Breaking payload changes require a new `event_version` or a new subject.
- MVP upload flow is: Admin upload -> Document Service stores status `queued` -> publish `doc.ingest`. There is no approve/reject step in this contract.

## Naming Convention

- Subjects use lower-case dot-separated names: `<domain>.<event_or_action>`.
- Event subjects use nouns and past-tense/intent names where useful, for example `doc.status` and `notify.doc_new`.
- Request-reply subjects are commands/actions, for example `rag.search`.

## Schema And Version Convention

JetStream event payloads keep business fields at the top level and add a small top-level metadata set:

```json
{
  "event_id": "uuid",
  "event_version": 1,
  "occurred_at": "2026-06-05T09:15:30Z"
}
```

The business fields documented below remain top-level fields, so existing DTOs can map directly. Consumers should ignore unknown fields. During early integration, consumers may accept legacy messages without metadata, but new publishers must include `event_id`, `event_version`, and `occurred_at` for JetStream events.

`rag.search` is synchronous core NATS request-reply and does not use this event metadata.

## Overview

| Subject | Type | Producer / Client | Consumer / Responder | Persistence | Delivery | Idempotency key |
| --- | --- | --- | --- | --- | --- | --- |
| `doc.ingest` | JetStream publish/subscribe | Document Service | RAG Worker | `DOC_EVENTS` | at-least-once, explicit ack | `event_id`; fallback `doc_id + "doc.ingest"` |
| `doc.status` | JetStream publish/subscribe | RAG Worker | Document Service | `DOC_EVENTS` | at-least-once, explicit ack | `event_id`; fallback `doc_id + status` |
| `doc.access` | JetStream publish/subscribe durable | Document Service | Query Service | `DOC_EVENTS` | at-least-once, durable, explicit ack | `event_id`; fallback `doc_id` with latest `occurred_at` |
| `notify.doc_new` | JetStream publish/subscribe | Document Service | Query Service | `NOTIFY_EVENTS` | at-least-once, explicit ack | `event_id`; fallback `doc_id + "doc_new"` |
| `rag.search` | Core NATS request-reply | MCP Service tool `rag_search` | RAG Worker | none | synchronous, timeout 10s | request-scoped; no persistence |

## Error And Retry Rules

- JetStream events (`doc.ingest`, `doc.status`, `doc.access`, `notify.doc_new`) are at-least-once. Consumers must be idempotent.
- Consumers deduplicate by `event_id` when present. If metadata is missing during transition, use the fallback key listed in the overview.
- Consumers must ack only after durable side effects complete.
- If processing fails with a retryable error, do not ack; JetStream will redeliver based on consumer config.
- If processing fails permanently, log the error, publish the appropriate domain failure event when one exists, then ack to avoid an infinite loop.
- `doc.status` is the only channel that updates ingestion status in Document Service PostgreSQL. RAG Worker must not write `doc_db`.
- `rag.search` is not persisted, not replayed, and not configured in JetStream. MCP Service uses a 10s timeout and handles timeout as a failed tool call.

## `doc.ingest`

Purpose: Admin upload completed and Document Service has created a `documents` row with status `queued`; RAG Worker starts ingestion.

| Field | Value |
| --- | --- |
| Owner | Backend Dev - Vu Quang Dung |
| Producer | Document Service |
| Consumer | RAG Worker |
| Type | JetStream publish/subscribe |
| Stream | `DOC_EVENTS` |
| Durability | RAG Worker should use a durable consumer such as `RAG_WORKER_INGEST` |
| Delivery | at-least-once, explicit ack |
| Retry | retry until ack; consumer should cap retries/dead-letter operationally if added later |
| Idempotency key | `event_id`; fallback `doc_id + "doc.ingest"` |

Payload example:

```json
{
  "event_id": "9f3fe29e-6f65-47c7-9bdf-474f3a18ac01",
  "event_version": 1,
  "occurred_at": "2026-06-05T09:15:30Z",
  "doc_id": "2e73f65e-0d2a-4f62-bb9f-f7c9a0bb2a5d",
  "gcs_key": "gs://rag-chatbot-docs/raw/2e73f65e-0d2a-4f62-bb9f-f7c9a0bb2a5d/policy.pdf",
  "document_name": "policy.pdf",
  "file_type": "pdf",
  "classification": "internal",
  "allowed_departments": [],
  "allowed_user_ids": []
}
```

Required fields: `event_id`, `event_version`, `occurred_at`, `doc_id`, `gcs_key`, `document_name`, `file_type`, `classification`, `allowed_departments`, `allowed_user_ids`.

## `doc.status`

Purpose: RAG Worker reports ingestion result. Document Service updates PostgreSQL; this is the only place ingestion status is updated in DB.

| Field | Value |
| --- | --- |
| Owner | Backend Dev - Vu Quang Dung |
| Producer | RAG Worker |
| Consumer | Document Service |
| Type | JetStream publish/subscribe |
| Stream | `DOC_EVENTS` |
| Durability | Document Service should use a durable consumer such as `DOCUMENT_SERVICE_STATUS` |
| Delivery | at-least-once, explicit ack |
| Retry | retry until Document Service stores the status update |
| Idempotency key | `event_id`; fallback `doc_id + status` |

Payload example:

```json
{
  "event_id": "29eb8513-8b61-4aae-88fd-8246514a5e02",
  "event_version": 1,
  "occurred_at": "2026-06-05T09:18:47Z",
  "doc_id": "2e73f65e-0d2a-4f62-bb9f-f7c9a0bb2a5d",
  "status": "indexed",
  "chunk_count": 42
}
```

Failure example:

```json
{
  "event_id": "09ab7744-2455-4d9a-93d0-900c11509ea4",
  "event_version": 1,
  "occurred_at": "2026-06-05T09:18:47Z",
  "doc_id": "2e73f65e-0d2a-4f62-bb9f-f7c9a0bb2a5d",
  "status": "failed",
  "error": "OCR service unavailable"
}
```

Required fields: `event_id`, `event_version`, `occurred_at`, `doc_id`, `status`.

Allowed `status`: `"indexed"` or `"failed"`.

Optional fields: `chunk_count`, `error`.

## `doc.access`

Purpose: Document Service publishes ACL changes. Query Service updates projection `query_svc.document_access` and must not read `doc_db` directly.

| Field | Value |
| --- | --- |
| Owner | Backend Dev - Vu Quang Dung |
| Producer | Document Service |
| Consumer | Query Service |
| Type | JetStream publish/subscribe durable |
| Stream | `DOC_EVENTS` |
| Durability | Query Service must use a durable consumer such as `QUERY_SERVICE_DOC_ACCESS` |
| Delivery | at-least-once, explicit ack |
| Retry | retry until Query Service upserts/deletes projection row |
| Idempotency key | `event_id`; fallback `doc_id` with latest `occurred_at` wins |

Payload example:

```json
{
  "event_id": "c685b749-bd9e-4210-b671-11381a638087",
  "event_version": 1,
  "occurred_at": "2026-06-05T09:15:31Z",
  "doc_id": "2e73f65e-0d2a-4f62-bb9f-f7c9a0bb2a5d",
  "classification": "secret",
  "allowed_departments": ["HR", "Finance"],
  "allowed_user_ids": [],
  "deleted": false
}
```

Delete example:

```json
{
  "event_id": "960a17bd-aa56-4cc2-ad07-080a983ed89e",
  "event_version": 1,
  "occurred_at": "2026-06-05T10:20:00Z",
  "doc_id": "2e73f65e-0d2a-4f62-bb9f-f7c9a0bb2a5d",
  "classification": "secret",
  "allowed_departments": ["HR", "Finance"],
  "allowed_user_ids": [],
  "deleted": true
}
```

Required fields: `event_id`, `event_version`, `occurred_at`, `doc_id`, `classification`, `allowed_departments`, `allowed_user_ids`, `deleted`.

## `notify.doc_new`

Purpose: Document Service publishes after receiving `doc.status` with `status="indexed"`. Query Service pushes SSE `/notifications` only to online users with access.

| Field | Value |
| --- | --- |
| Owner | Backend Dev - Vu Quang Dung |
| Producer | Document Service |
| Consumer | Query Service |
| Type | JetStream publish/subscribe |
| Stream | `NOTIFY_EVENTS` |
| Durability | Query Service should use a durable consumer such as `QUERY_SERVICE_NOTIFY_DOC_NEW` |
| Delivery | at-least-once, explicit ack |
| Retry | retry until Query Service records/pushes notification handling |
| Idempotency key | `event_id`; fallback `doc_id + "doc_new"` |

Payload example:

```json
{
  "event_id": "f1d96582-2453-4e05-8995-2f353d02fae0",
  "event_version": 1,
  "occurred_at": "2026-06-05T09:18:49Z",
  "doc_id": "2e73f65e-0d2a-4f62-bb9f-f7c9a0bb2a5d",
  "document_name": "Travel Policy 2026.pdf",
  "classification": "internal",
  "allowed_departments": [],
  "allowed_user_ids": []
}
```

Required fields: `event_id`, `event_version`, `occurred_at`, `doc_id`, `document_name`, `classification`, `allowed_departments`, `allowed_user_ids`.

## `rag.search`

Purpose: MCP Service tool `rag_search` asks RAG Worker for retrieval candidates. This is synchronous and not persisted.

| Field | Value |
| --- | --- |
| Owner | Registered here by Backend Dev; payload owned by RAG Engineer |
| Client | MCP Service tool `rag_search` |
| Responder | RAG Worker |
| Type | Core NATS request-reply |
| Persistence | none; do not add to JetStream |
| Timeout | 10s |
| Idempotency key | none; request-scoped |

Request example:

```json
{
  "query_text": "chinh sach cong tac phi",
  "document_ids": [
    "2e73f65e-0d2a-4f62-bb9f-f7c9a0bb2a5d"
  ],
  "top_k": 5
}
```

Request required fields: `query_text`, `document_ids`, `top_k`.

Reply example:

```json
{
  "results": [
    {
      "section_id": "chunk-9f1d",
      "document_id": "2e73f65e-0d2a-4f62-bb9f-f7c9a0bb2a5d",
      "document_name": "Travel Policy 2026.pdf",
      "caption": "Flight reimbursement",
      "section_content": "Employees may claim eligible flight expenses...",
      "heading_path": ["Travel Policy", "Reimbursement"],
      "score": 0.87,
      "source_gcs_uri": "gs://rag-chatbot-docs/raw/2e73f65e/policy.pdf",
      "markdown_gcs_uri": "gs://rag-chatbot-docs/processed/2e73f65e/policy.md"
    }
  ]
}
```

Reply required fields: `results`.

Each result required fields: `section_id`, `document_id`, `document_name`, `caption`, `section_content`, `heading_path`, `score`, `source_gcs_uri`, `markdown_gcs_uri`.

Compatibility note: `section_id` maps to the RAG Worker chunk identifier if the implementation uses `chunk_id` internally. `section_content` maps to parent/section text returned for LLM context.
