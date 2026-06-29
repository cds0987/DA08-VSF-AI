# Backend Citation Contract Plan

## Goal

Make Query Service and Document Service responses match the current chat frontend so every RAG citation opens in the live SSE answer and still opens after conversation history reload.

This document is the backend handoff contract. Field names and response envelopes below are normative; do not rename them or wrap them in another object without coordinating a frontend change.

## Frontend Compatibility Snapshot

The frontend currently consumes these TypeScript shapes:

```ts
interface QuerySource {
  document_id?: string
  document_name: string
  caption: string
  heading_path: string[]
  score: number
  source_gcs_uri?: string
  page_number?: number | null
}

interface ConversationHistoryResponse {
  messages: Array<{
    role: "user" | "assistant"
    content: string
    created_at: string
    sources?: QuerySource[]
  }>
}

interface DocumentFileResponse {
  url: string
  file_type: string
  expires_in: number
}
```

The optional markers on `document_id`, `source_gcs_uri`, `page_number`, and history `sources` exist only so the frontend can read legacy backend data. They do not make those fields optional for newly generated RAG sources.

Relevant frontend files:

- `src/frontend/chat/app/types/index.ts`
- `src/frontend/chat/app/stores/chat.ts`
- `src/frontend/chat/app/components/SourcePanel.vue`
- `src/frontend/chat/app/lib/api/documentService.ts`

## Query Source Contract

Every source in a new RAG response MUST use this exact JSON shape:

```json
{
  "document_id": "dddddddd-0002-4000-8000-000000000002",
  "document_name": "leave_policy.pdf",
  "caption": "Employees receive 12 days of annual leave.",
  "heading_path": ["HR", "Leave", "Annual leave"],
  "score": 0.85,
  "source_gcs_uri": "gs://rag-chatbot-docs/raw/dddddddd-0002-4000-8000-000000000002/leave_policy.pdf",
  "page_number": 3
}
```

Field requirements:

| Field | New responses | Type | Frontend use |
| --- | --- | --- | --- |
| `document_id` | Required, non-empty | string UUID | Calls Document Service and is the primary citation key |
| `document_name` | Required, non-empty | string | Display name and file-extension fallback |
| `caption` | Required | string | Citation label and text highlighting |
| `heading_path` | Required | string array | Breadcrumb; use `[]` when unavailable |
| `score` | Required | finite number | Query source metadata |
| `source_gcs_uri` | Required for RAG sources | string | Diagnostics and legacy ID fallback only |
| `page_number` | Required key, nullable | positive integer or `null` | Opens PDF at the cited page |

Rules:

1. `document_id` MUST be the same ID accepted by Document Service. Do not send a chunk ID, vector ID, ingestion job ID, filename, or storage key in this field.
2. `page_number` is 1-based. Return `null` when no page is available. Do not send `0`, a numeric string, or omit it in new responses.
3. `heading_path` must always be an array, never `null` or a delimiter-joined string.
4. Keep the exact snake_case names. The frontend does not consume `documentId`, `file_name`, `source_uri`, `source_s3_uri`, or `page`.
5. The frontend can recover an ID from the exact URI segment `/raw/{document_id}/` for old rows only. Current URIs without this segment cannot be recovered, so this fallback MUST NOT replace an explicit `document_id` in new responses.

## Live SSE Contract

The final SSE data frame MUST be a JSON object containing `done: true`, a string `session_id`, and a `sources` array:

```text
data: {"done":true,"sources":[{"document_id":"dddddddd-0002-4000-8000-000000000002","document_name":"leave_policy.pdf","caption":"Employees receive 12 days of annual leave.","heading_path":["HR","Leave"],"score":0.85,"source_gcs_uri":"gs://rag-chatbot-docs/raw/dddddddd-0002-4000-8000-000000000002/leave_policy.pdf","page_number":3}],"session_id":"query-session-uuid"}

```

Compatibility requirements:

- Keep the existing `data: <json>` SSE framing.
- Additional fields such as `fallback`, `cached`, `agent_mode`, or `iterations` are allowed.
- `sources` must be an array; use `[]` when no RAG source exists.
- Emit the complete source objects in the final done payload. Token frames do not need sources.
- All orchestration modes, including LangGraph and legacy/non-LangGraph paths, must emit the same source shape.

## Conversation History Contract

`GET /api/query/conversations?limit=500&offset=0` through the gateway MUST return this top-level envelope:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "How many annual leave days do I receive?",
      "created_at": "2026-06-11T03:00:00Z",
      "sources": []
    },
    {
      "role": "assistant",
      "content": "Employees receive 12 days of annual leave.",
      "created_at": "2026-06-11T03:00:02Z",
      "sources": [
        {
          "document_id": "dddddddd-0002-4000-8000-000000000002",
          "document_name": "leave_policy.pdf",
          "caption": "Employees receive 12 days of annual leave.",
          "heading_path": ["HR", "Leave"],
          "score": 0.85,
          "source_gcs_uri": "gs://rag-chatbot-docs/raw/dddddddd-0002-4000-8000-000000000002/leave_policy.pdf",
          "page_number": 3
        }
      ]
    }
  ]
}
```

History requirements:

- Persist the exact source objects attached to the assistant message, not only the answer text.
- Return `sources` on every message. Prefer `[]` for user messages and assistant messages without citations.
- Preserve `document_id`, `document_name`, `caption`, `heading_path`, `score`, `source_gcs_uri`, and `page_number` across save and reload.
- Keep old JSONB rows readable. Missing new fields must not fail validation of the entire history response.
- For old rows, backfill `document_id` only when it can be derived unambiguously from `/raw/{document_id}/`; otherwise return the row without inventing an ID. New rows must always persist the explicit ID.

## Document File Contract

After a citation is selected, the frontend calls:

```text
GET /api/documents/{document_id}/file
Authorization: Bearer <same user token>
```

The gateway may strip `/api/documents` before forwarding to the internal Document Service route `GET /documents/{document_id}/file`. The public gateway path above is what must work for the frontend.

Successful response:

```json
{
  "url": "https://storage.example/signed-object-url",
  "file_type": "pdf",
  "expires_in": 300
}
```

Requirements:

1. Return HTTP 200 only after applying the existing document ACL for the authenticated user.
2. `url` must be a non-empty browser-accessible signed HTTPS URL for the original file bytes.
3. `file_type` must be lowercase and have no leading dot. Supported frontend values are exactly `pdf`, `docx`, `txt`, `xlsx`, `csv`, `pptx`, and `md`.
4. `expires_in` must be a positive number in seconds and match the signed URL lifetime.
5. The ID in this request must be the same `document_id` emitted by Query Service.
6. Preserve normal auth/error semantics: `401` unauthenticated, `403` unauthorized by ACL, and `404` unknown document.

## Storage CORS Contract

For `docx`, `txt`, `xlsx`, `csv`, `pptx`, and `md`, the browser fetches the signed URL directly. PDF.js also loads the PDF URL in the browser. Therefore the bucket/object response must allow the deployed frontend origin.

At minimum, configure storage CORS for:

- Methods: `GET`, `HEAD`
- Request headers: `Range` where required by PDF/range loading
- Response headers exposed to the browser: `Accept-Ranges`, `Content-Length`, `Content-Range`, `Content-Type`
- Origins: the actual deployed frontend origin; use `*` only if consistent with the security policy

A signed URL that works in curl but is blocked by browser CORS does not satisfy this contract.

## Backend Implementation Plan

1. Extend the public Query Service `Source` schema and internal/LangGraph `SourceDoc` with `document_id` and nullable `page_number`.
2. Update MCP/vector search output so each hit carries the canonical Document Service ID and 1-based page number when known.
3. Preserve all source fields when `act_node` maps MCP `rag_search` results into graph state.
4. Update the legacy orchestration `_source_payload()` path to emit the identical shape.
5. Validate before the final SSE frame that every new RAG source has a non-empty canonical `document_id`.
6. Persist the complete source list in `query_svc.messages.sources` for assistant messages.
7. Add `sources` to each message schema returned by `GET /conversations` without breaking old JSONB rows.
8. Confirm the gateway forwards `GET /api/documents/{id}/file` with the user Authorization header to Document Service.
9. Confirm Document Service returns the exact `url`, `file_type`, `expires_in` response and that storage CORS permits browser reads.

## Required Tests

### Query Service

1. Final SSE test asserts `done === true`, `session_id` is a string, and `sources` is an array.
2. Every new RAG source has all seven keys with the exact names in this document.
3. `document_id` is non-empty and resolves to the same Document Service record used during ingestion.
4. PDF sources preserve a positive 1-based `page_number`; unavailable pages return JSON `null`.
5. LangGraph and legacy modes produce the same source schema.
6. A source from MCP cannot lose `document_id` or `page_number` during mapping.

### History

1. Save an assistant message with the canonical source fixture above.
2. Fetch `/conversations` and assert the source object is value-equal for all seven fields.
3. Assert user messages return `sources: []`.
4. Load an old source object without `document_id` and `page_number`; the endpoint must still return HTTP 200.
5. Test legacy backfill for a URI containing `/raw/{document_id}/` and no backfill for ambiguous URIs.

### Document Service and Browser Integration

Run the same integration case for each supported extension:

```text
pdf, docx, txt, xlsx, csv, pptx, md
```

For each case:

1. Obtain the source from the final SSE payload.
2. Call `GET /api/documents/{source.document_id}/file` using the same user token.
3. Assert HTTP 200 and exact response keys `url`, `file_type`, `expires_in`.
4. Assert `file_type` equals the expected lowercase extension.
5. Fetch the returned URL from a browser-origin test and assert CORS permits reading the bytes.
6. Reload `/api/query/conversations` and repeat the file request using the persisted source ID.

Also test `401`, `403`, and `404` responses and ensure one invalid citation does not invalidate unrelated history messages.

## Acceptance Criteria

- A live final SSE source maps directly to the frontend `QuerySource` shape without renaming or transformation.
- Clicking a live citation successfully calls `/api/documents/{document_id}/file` and renders the original file.
- PDF, DOCX, TXT, XLSX, CSV, PPTX, and MD all return supported lowercase `file_type` values and browser-readable signed URLs.
- Reloading chat history returns the same citation fields and the citation still opens.
- No MCP, LangGraph, legacy orchestration, persistence, or serialization step drops `document_id` or `page_number`.
- Existing conversation rows remain readable without requiring a destructive migration.
- Backend contract tests use the canonical fixtures in this document and pass before deployment.
