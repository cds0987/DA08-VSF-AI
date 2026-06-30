# infra/nats - NATS Contract And JetStream Config

Owner: Backend Dev - Vu Quang Dung.

- [subjects.md](subjects.md): source of truth for NATS subjects, payloads, producers, consumers, delivery, retry, and idempotency.
- [jetstream.conf](jetstream.conf): NATS server JetStream config plus stream bootstrap commands for `doc.*`, `notify.*`, and `hr.*` events.

Current JetStream event streams:

- `DOC_EVENTS`: `doc.ingest`, `doc.status`, `doc.access`; limits retention, max age 7 days, duplicate window 2 minutes.
- `NOTIFY_EVENTS`: `notify.doc_new`; limits retention, max age 3 days, duplicate window 2 minutes.
- `HR_EVENTS`: `hr.*` namespace plus exact subject `hr.employee_profile.updated`; limits retention, max age 30 days, duplicate window 2 minutes.

Current core NATS request-reply subjects:

- `rag.search`: MCP Service tool `rag_search` asks RAG Worker for retrieval candidates with a 10s timeout. This subject must not be added to JetStream.

Suggested durable consumers:

- `RAG_WORKER_INGEST`: filters `doc.ingest`, explicit ack, deliver all, max deliver 10.
- `DOCUMENT_SERVICE_STATUS`: filters `doc.status`, explicit ack, deliver all, max deliver 10.
- `QUERY_SERVICE_DOC_ACCESS`: filters `doc.access`, explicit ack, deliver all, max deliver 20.
- `QUERY_SERVICE_NOTIFY_DOC_NEW`: filters `notify.doc_new`, explicit ack, deliver new or all, max deliver 5.
- `QUERY_SERVICE_USER_ACCESS_PROFILE`: filters `hr.employee_profile.updated`, explicit ack, deliver all, max deliver 20.

DevOps should mount `jetstream.conf` into the NATS container and start `nats-server` with that config. Do not add `rag.search` to JetStream; it is synchronous core NATS request-reply.
