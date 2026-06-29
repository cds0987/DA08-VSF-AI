---
last-verified: 59551e39 (2026-06-29)
code-refs:
  - infra/nats/event-contracts.yaml
  - infra/nats/subjects.md
  - infra/ci/nats_contract_lint.py
---

# Hợp đồng NATS (subjects + payload)

T1 — sinh từ code. Nguồn sự thật máy đọc: `event-contracts.yaml`. Gate
`nats_contract_lint.py` (thuần AST + parse markdown, lệch = exit 1):

- **publisher**: tại `publisher_marker` gom string-literal dict key →
  `business_required ⊆ key` (publisher gửi đủ).
- **consumer**: tại `consumer_markers` gom field "required" (`_required_str(_,"K")`
  + `payload["K"]`) → PHẢI ⊆ `meta ∪ business_required ∪ business_optional`
  (consumer không require field contract không đảm bảo → else NAK-storm/drop).
- **subjects.md**: dòng "Required fields:" mỗi subject PHẢI == `sorted(meta + business_required)`.

`meta` = `event_id, event_version, occurred_at` (wrapper publish tự thêm; linter không
soi meta ở publisher).

## Subjects

| subject                        | stream        | publisher        | consumer(s)    | business_required | business_optional |
|--------------------------------|---------------|------------------|----------------|-------------------|-------------------|
| `doc.ingest`                   | DOC_EVENTS    | document-service | rag-worker     | doc_id, gcs_key, document_name, file_type, classification, allowed_departments, allowed_user_ids | — |
| `doc.status`                   | DOC_EVENTS    | rag-worker       | document-service | doc_id, status | chunk_count, error |
| `doc.access`                   | DOC_EVENTS    | document-service | query-service  | doc_id, classification, allowed_departments, allowed_user_ids, deleted | — |
| `hr.employee_profile.updated`  | HR_EVENTS     | hr-service       | query-service  | user_id, account_type, department, employment_status | — |
| `notify.doc_new`               | NOTIFY_EVENTS | document-service | query-service  | doc_id, document_name, classification, allowed_departments, allowed_user_ids | — |
| `user.created`                 | USER_EVENTS   | user-service     | hr-service     | user_id, email, role, account_type, is_active | department |
| `user.updated`                 | USER_EVENTS   | user-service     | hr-service     | user_id, email, role, account_type, is_active | department |
| `user.deactivated`             | USER_EVENTS   | user-service     | hr-service     | user_id, email, role, account_type, is_active | department |
| `user.deleted`                 | USER_EVENTS   | user-service     | hr-service     | user_id, email, role, account_type, is_active | department |

`user.*` cùng payload (`build_user_event`).

## Gap có chủ đích: department

`department` KHÔNG nằm trong `business_required` của `user.*`: user-service CỐ Ý
không gửi (HR Service tự quản department). Để `business_optional` → consumer HR đọc
`.get("department","")`. Nguồn sự thật department là hr-service, không phải event
user.* (xem `jwt-claims.md` — department cũng KHÔNG trong token).
