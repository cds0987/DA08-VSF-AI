# NATS Test Instructions

Owner: Backend Dev - Vu Quang Dung.

Use this file to verify the NATS contract and JetStream config in `infra/nats/` before handing work to Document Service, RAG Worker, Query Service, HR Service, or DevOps.

## What To Test

1. `jetstream.conf` must start a NATS server with JetStream enabled.
2. `subjects.md` must stay aligned with the stream layout in `jetstream.conf`.
3. `rag.search` must stay out of JetStream because it is core request-reply only.
4. `doc.ingest`, `doc.status`, `doc.access`, `hr.employee_profile.updated`, and `notify.doc_new` must remain at-least-once JetStream events.
5. `hr.employee_profile.updated` must stay in `HR_EVENTS` with a durable Query Service consumer for `query_svc.user_access_profile`.

## Minimal Local Validation

If a NATS container is already running, copy the config into the container and run config test:

```bash
docker cp infra/nats/jetstream.conf da08-nats:/tmp/jetstream.conf
docker exec da08-nats /nats-server -t -c /tmp/jetstream.conf
```

Expected result:

```text
nats-server: configuration file /tmp/jetstream.conf is valid
```

If the container name is different, use the active NATS container name from `docker ps`.

## Contract Checks

Review these points in `subjects.md`:

- `doc.ingest` payload contains `doc_id`, `gcs_key`, `document_name`, `file_type`, `classification`, `allowed_departments`, `allowed_user_ids`.
- `doc.status` payload contains `doc_id`, `status`, and optional `chunk_count` or `error`.
- `doc.access` payload contains `classification`, ACL fields, and `deleted`.
- `hr.employee_profile.updated` payload contains `event_id`, `event_version`, `occurred_at`, `user_id`, `account_type`, `department`, `employment_status`.
- `notify.doc_new` payload contains `doc_id`, `document_name`, and ACL fields.
- `rag.search` request contains `query_text`, `document_ids`, `top_k`, and uses timeout 10s.

## Who Publishes What

| Subject | Publisher | Subscriber / Responder |
| --- | --- | --- |
| `doc.ingest` | Document Service | RAG Worker |
| `doc.status` | RAG Worker | Document Service |
| `doc.access` | Document Service | Query Service |
| `hr.employee_profile.updated` | HR Service | Query Service |
| `notify.doc_new` | Document Service | Query Service |
| `rag.search` | MCP Service tool `rag_search` | RAG Worker |

## One Minute Flow

```text
Admin upload
  -> Document Service saves file to GCS
  -> Document Service creates document row with status `queued`
  -> Document Service publishes `doc.ingest`
  -> RAG Worker ingests and indexes
  -> RAG Worker publishes `doc.status`
  -> Document Service updates PostgreSQL status
  -> if status = `indexed`, Document Service publishes `notify.doc_new`
  -> Query Service updates ACL/projection from `doc.access`
  -> Query Service pushes SSE notifications to online users

HR profile update:
  -> HR Service updates employee profile, department, or employment status
  -> HR Service publishes `hr.employee_profile.updated`
  -> Query Service durable consumer `QUERY_SERVICE_USER_ACCESS_PROFILE`
  -> Query Service upserts projection `query_svc.user_access_profile`

Query path:
  -> MCP Service tool `rag_search`
  -> core NATS request `rag.search`
  -> RAG Worker returns top chunks
  -> MCP Service reranks and returns Top-3
```

## Stream Expectations

`jetstream.conf` is expected to describe:

- `DOC_EVENTS` for `doc.ingest`, `doc.status`, `doc.access`
- `NOTIFY_EVENTS` for `notify.doc_new`
- `HR_EVENTS` for `hr.*` namespace plus exact subject `hr.employee_profile.updated`
- file storage
- max age about 7 days for document events
- max age about 3 days for notification events
- max age about 30 days for HR profile events
- duplicate window about 2 minutes

Durable consumer expectations:

- `RAG_WORKER_INGEST` filters `doc.ingest`, ack explicit, deliver all, max deliver 10.
- `DOCUMENT_SERVICE_STATUS` filters `doc.status`, ack explicit, deliver all, max deliver 10.
- `QUERY_SERVICE_DOC_ACCESS` filters `doc.access`, ack explicit, deliver all, max deliver 20.
- `QUERY_SERVICE_NOTIFY_DOC_NEW` filters `notify.doc_new`, ack explicit, deliver new or all, max deliver 5.
- `QUERY_SERVICE_USER_ACCESS_PROFILE` filters `hr.employee_profile.updated`, ack explicit, deliver all, max deliver 20.

## Acceptance Checklist

- [ ] `nats-server -t -c /tmp/jetstream.conf` passes
- [ ] `subjects.md` still matches the approved contract
- [ ] `HR_EVENTS` includes `hr.employee_profile.updated` and uses duplicate window about 2 minutes
- [ ] Query Service durable consumer `QUERY_SERVICE_USER_ACCESS_PROFILE` is documented for `hr.employee_profile.updated`
- [ ] `rag.search` is not added to JetStream
- [ ] DevOps knows to mount `jetstream.conf` into the NATS container

## Notes

- Do not change `docker-compose.yml` from this folder.
- Do not add secrets here.
- If a subject or payload must change, update `subjects.md` first and notify all producers and consumers.
