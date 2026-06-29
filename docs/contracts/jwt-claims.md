---
last-verified: 59551e39 (2026-06-29)
code-refs:
  - infra/auth/jwt-claims-contract.yaml
  - infra/ci/jwt_claims_lint.py
  - src/user-service/app/infrastructure/security/jwt_token_service.py (create_access_token)
  - src/query-service/app/infrastructure/auth/auth_service.py (_authenticate_jwt)
  - src/document-service/app/interfaces/api/dependencies.py (get_current_user)
  - src/hr-service/app/api/auth.py (require_admin_jwt)
---

# Hợp đồng JWT claims (access token liên-service)

T1 — sinh từ code. user-service PHÁT token; query/document/hr-service GIẢI MÃ. Nguồn
sự thật: `jwt-claims-contract.yaml`. Gate `jwt_claims_lint.py` (thuần AST, lệch = exit 1).

- `algorithm`: HS256
- `secret_env`: `JWT_SECRET_KEY` (gate D ép biến này hiện diện trong config mọi service)

## Claims user-service PHÁT (`issued_claims` — snapshot khoá)

`sub`, `user_id`, `role`, `account_type`, `jti`, `iat`, `exp`.

- Producer: user-service `create_access_token`. Gate A ép producer phát ĐÚNG tập này
  (dư/thiếu/rename = đỏ → buộc review consumer, chống fail-open kiểu rename account_type).
- `compat_aliases: [id]` — consumer đọc dự phòng (any-of `sub`/`id`/`user_id`); producer
  KHÔNG phát, chỉ là fallback identity, không đưa vào issued.

## Consumer (decoder)

| service          | decoder file                                         | marker |
|------------------|------------------------------------------------------|--------|
| query-service    | `…/infrastructure/auth/auth_service.py`              | `_authenticate_jwt` |
| document-service | `…/interfaces/api/dependencies.py`                   | `get_current_user` |
| hr-service       | `…/api/auth.py`                                       | `require_admin_jwt` |

- Gate B: claim consumer require cứng (`payload["X"]`) ⊆ `issued ∪ compat_aliases`
  (else 401 fail-closed mọi token).
- Gate C: consumer đọc claim ACL-critical mà producer không phát → PHẢI khai
  `known_unissued_acl_reads` (chống fail-open). Hiện `known_unissued_acl_reads: {}` (RỖNG).

## Gap: `department` KHÔNG nằm trong token

`acl_critical = [role, account_type, department]` nhưng `department` KHÔNG ∈
`issued_claims`. Đây là gap đã KHẮC PHỤC (2026-06-21): document-service không còn đọc
`department` từ token — department lấy SỐNG từ hr-service (nguồn sự thật) ở tầng ACL
(`with_live_department`). Vì `known_unissued_acl_reads` rỗng, gate C ép: KHÔNG consumer
nào được đọc `department` từ token.

Claim ACL THỰC SỰ trong token: `role` + `account_type`.
