# infra/nats - NATS Contract And JetStream Config

Owner: Backend Dev - Vu Quang Dung.

- [subjects.md](subjects.md): source of truth for NATS subjects, payloads, producers, consumers, delivery, retry, and idempotency.
- [jetstream.conf](jetstream.conf): NATS server JetStream config plus stream bootstrap commands for `doc.*` and `notify.*`.

DevOps should mount `jetstream.conf` into the NATS container and start `nats-server` with that config. Do not add `rag.search` to JetStream; it is synchronous core NATS request-reply.

See also: [team ownership](../../docs/team-ownership.md).
