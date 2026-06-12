# Hướng dẫn dev — Chuẩn hóa DB Migration + Cơ chế đồng bộ danh tính

**Cập nhật:** 2026-06-12 · Người soạn: Nguyen Tran
**Đối tượng:** dev phụ trách `document-service`, `user-service`, `hr-service`
**Mục tiêu:** giải tận gốc 2 vấn đề — (1) mỗi service quản lý schema một kiểu → kéo về **Alembic** đồng bộ; (2) thêm nhân viên ở một service nhưng service khác không biết → **cơ chế đồng bộ bằng event**.

> Đọc kèm: [04-definition-of-done.md](04-definition-of-done.md) (tiêu chí done), [dev.md](dev.md) (clean architecture + cách viết test), [infra/nats/subjects.md](../../infra/nats/subjects.md) (hợp đồng event — **source of truth**).

## Trạng thái triển khai (2026-06-12)

✅ **ĐÃ CODE** (nhánh nguyendev, chờ CI + deploy verify):
- document-service & user-service → Alembic (`migrations/` + `alembic.ini` + baseline `0001`); compose + e2e có `doc-migrate`/`user-migrate`; bỏ runner tự chế user-service.
- hr-service lazy auto-create leave_balance (flag `auto_provision_leave_balance`, ON mặc định).
- Event `user.*`: subjects.md + stream `USER_EVENTS`; user-service publisher + emit ở set-active + backfill script; hr-service subscriber + provision idempotent (flag `user_events_enabled`).
- Test fail-fast (fake, KHÔNG NATS thật, KHÔNG sleep): hr `test_user_events_handler.py`, user `test_user_events.py`.

⏳ **CÒN THAO TÁC OPS MỘT LẦN trên VM**: `alembic stamp` cho DB cũ + chạy backfill go-live (xem §1.4 + FAQ).

### FAQ — "stamp" có phải vá tay không?

- **Data lệch cũ (admin chưa có hồ sơ HR): KHÔNG cần tay.** hr lazy auto-create tự tạo khi hỏi; hoặc backfill `user.created` (lệnh tự động, không sửa SQL tay).
- **`alembic stamp 0001_baseline`: CÓ, đúng một lần / mỗi DB cũ.** KHÔNG phải sửa data — chỉ "khai báo DB đang ở baseline" để Alembic không tạo lại bảng đã tồn tại. DB mới (e2e/CI) `upgrade head` chạy thẳng, không cần stamp.

---

## 0. Bối cảnh — vì sao cần làm

### Vấn đề 1: 4 service quản lý DB 4 kiểu

| Service | Cách hiện tại | Migrate one-shot khi deploy |
|---------|---------------|-----------------------------|
| rag-worker | ✅ Alembic | ✅ `rag-migrate` |
| hr-service | ✅ Alembic | ✅ `hr-migrate` |
| **document-service** | ❌ 1 file `.sql` thô (`001_rename_s3_key_to_gcs_key.sql`), **không runner, không create schema ở prod** | ❌ **KHÔNG có** |
| **user-service** | ⚠️ Runner tự chế (`scripts/migrate.py` + `.sql` + bảng `migration_history`) | ⚠️ Riêng, lệch chuẩn |

Hệ quả document-service: schema `doc_svc` trên VM hiện được dựng **mơ hồ** (tạo tay 1 lần?) → nếu DB reset thì service gãy, không tự dựng lại được. Trái nguyên tắc "mọi thứ từ git, tự recover".

### Vấn đề 2: Không có cơ chế đồng bộ danh tính

- `user-service` **không bắn event** khi có user mới.
- `hr-service` **không lắng nghe** user mới.
- → Admin demo thật (`admin@company.com`, user_id `4f44e7f7...`) **không có hồ sơ trong hr** → hỏi "số ngày phép còn lại" trả 404 → NO_INFO.
- Migration `0001` của hr chỉ seed 2 user **hư cấu** (`1111...`, `2222...`) không ai đăng nhập được.

Boundary đúng: 3 service **không chung DB, không gọi chéo DB**. Chúng chỉ tham chiếu **user_id (UUID)** do user-service cấp trong JWT (`sub`, `role`, `department`). Đồng bộ phải qua **event (NATS)**, KHÔNG cho hr đọc thẳng DB user-service.

---

## PHẦN 1 — Refactor `document-service` & `user-service` về Alembic

Mục tiêu: cả 4 service dùng **CÙNG một pattern** y hệt hr-service. Mẫu tham chiếu: [src/hr-service/migrations/env.py](../../src/hr-service/migrations/env.py), [src/hr-service/alembic.ini](../../src/hr-service/alembic.ini), block `hr-migrate` trong [docker-compose.yml](../../docker-compose.yml).

### 1.1. Pattern chuẩn (áp dụng cho cả 2 service)

Mỗi service cần:
```
src/<svc>/
├── alembic.ini                      # script_location = migrations ; sqlalchemy.url = (để trống)
├── migrations/
│   ├── env.py                       # copy từ hr, đổi tên biến env DB + import Base đúng service
│   ├── script.py.mako               # template chuẩn của alembic
│   └── versions/
│       └── 0001_baseline.py         # dựng đủ schema theo models hiện tại
```

**`env.py`** — copy nguyên từ [hr env.py](../../src/hr-service/migrations/env.py), chỉ đổi:
- `from app.infrastructure.db.models import Base` (đúng path từng service).
- Hàm `_database_url()`: đọc đúng biến env của service (xem 1.2 / 1.3).
- Giữ `include_schemas=True` (vì dùng schema riêng `doc_svc` / `user_svc`).

**`alembic.ini`** (giống hr):
```ini
[alembic]
script_location = migrations
sqlalchemy.url =
```

**Yêu cầu requirements.txt:** thêm `alembic` nếu chưa có (hr đã có — copy version cho đồng bộ).

### 1.2. document-service — chi tiết

DB url: dùng biến runtime hiện có (kiểm `src/document-service/app/core/config.py` → `database_url`). Đặt env ưu tiên `DOC_DATABASE_URL` rồi fallback `DATABASE_URL` (cùng triết lý hr).

Models cần dựng (xem [src/document-service/app/infrastructure/db/models.py](../../src/document-service/app/infrastructure/db/models.py)):
- schema `doc_svc`
- bảng `documents` (id, name, file_type, **gcs_key** — đã rename, status, uploaded_by, classification, allowed_departments `ARRAY(text)`, allowed_user_ids `ARRAY(text)`, chunk_count, error_message, created_at, updated_at, deleted_at)
- bảng `audit_logs`

**Baseline `0001_baseline.py`:**
- `op.execute("CREATE SCHEMA IF NOT EXISTS doc_svc")`
- `op.create_table(...)` đủ 2 bảng theo models **ở trạng thái HIỆN TẠI** (tức cột đã là `gcs_key`, KHÔNG tạo `s3_key` rồi rename) → **nuốt luôn** ý nghĩa của file `001_rename_s3_key_to_gcs_key.sql`.
- Tạo index như model khai báo (`status`, `uploaded_by` index=True).
- `downgrade()` drop bảng + schema.

**Xóa** `migrations/001_rename_s3_key_to_gcs_key.sql` sau khi baseline đã phản ánh schema cuối.

**docker-compose.yml** — thêm `doc-migrate` (copy block `hr-migrate`, đổi tên + env_file `document-service.env`), và cho `document-service` `depends_on: doc-migrate: condition: service_completed_successfully`.

### 1.3. user-service — chi tiết (cẩn thận hơn vì đang có runner riêng)

DB url: giữ tương thích — đọc `USER_DATABASE_URL` → `DATABASE_URL` (xem `scripts/migrate.py` đang đọc cả hai).

Models cần dựng (xem [src/user-service/app/infrastructure/db/models.py](../../src/user-service/app/infrastructure/db/models.py)):
- schema `user_svc`
- bảng `users` (id, email unique, hashed_password, auth_provider, role, **account_type** + CheckConstraint `internal/external`, is_active, department, failed_login_count, locked_until, created_at, updated_at)
- bảng `refresh_tokens`, bảng `audit_logs`

**Baseline `0001_baseline.py`:** dựng đủ 3 bảng theo model HIỆN TẠI (gồm cột `account_type` — **gộp** ý nghĩa `001_add_users_account_type.sql`).

**Gỡ bỏ sau khi Alembic chạy ổn:**
- `scripts/migrate.py` (runner tự chế)
- bảng `migration_history` (runner tự chế dùng) — drop trong baseline hoặc migration dọn dẹp riêng.
- thư mục `.sql` cũ.

**docker-compose.yml** — thêm `user-migrate` one-shot tương tự; `user-service` depends_on nó.

### 1.4. ⚠️ BẪY LỚN — chuyển DB prod đang có data (VM)

Bảng đã tồn tại trên Cloud SQL → chạy `alembic upgrade` baseline sẽ lỗi `relation already exists`. Quy trình an toàn:

| Môi trường | Lệnh | Vì sao |
|-----------|------|--------|
| DB mới (local / e2e / CI) | `alembic upgrade head` | Tạo từ đầu, sạch |
| **DB cũ đang chạy (VM prod)** | **`alembic stamp 0001` MỘT LẦN** (thủ công, trước khi bật `*-migrate` trong compose) | Đánh dấu "đã ở baseline" mà KHÔNG chạy lại CREATE. Từ `0002` trở đi mới thật sự apply |

- Baseline nên dùng guard an toàn 2 chiều: `CREATE SCHEMA IF NOT EXISTS`, và cân nhắc `op.create_table(..., if_not_exists=True)` (Alembic 1.13+) hoặc kiểm tra `inspect(conn).has_table(...)`.
- **Trước khi đụng VM**: backup DB (`pg_dump`) — đây là thao tác khó đảo ngược.
- DevOps phải đảm bảo `CREATE DATABASE` đã có trên Cloud SQL (như note `hr-migrate`).

### 1.5. Test bắt buộc (theo dev.md §3)
- CI e2e: DB mới → `alembic upgrade head` PASS, tạo đủ bảng (assert qua `information_schema`).
- `upgrade head` rồi `downgrade base` rồi `upgrade head` lại → không lỗi (idempotent 2 chiều).
- Parity: model SQLAlchemy ↔ schema sau migrate khớp (không thừa/thiếu cột).

---

## PHẦN 2 — Cơ chế đồng bộ danh tính (event-driven)

### 2.1. Nguyên tắc thiết kế

- **user-service = cổng vào danh tính** (không có tài khoản thì không là nhân viên) → nó **phát** sự kiện vòng đời user.
- **hr-service = chủ hồ sơ nhân sự** → nó **nghe** và tự cấp phát/cập nhật hồ sơ.
- Tuyệt đối KHÔNG cho hr đọc thẳng DB user-service. Chỉ giao tiếp qua **event NATS** hoặc API công khai.
- Mọi consumer phải **idempotent** (at-least-once, dedupe theo `event_id`) — theo [subjects.md](../../infra/nats/subjects.md).

### 2.2. Subject mới cần thêm vào hợp đồng

⚠️ [subjects.md](../../infra/nats/subjects.md) do **Backend Dev (Vu Quang Dung) sở hữu** — **phải báo + duyệt trước khi code** (quy tắc "Change Rules" trong file đó). Đề xuất thêm:

| Subject | Producer | Consumer | Stream | Ý nghĩa |
|---------|----------|----------|--------|---------|
| `user.created` | user-service | hr-service (+tương lai) | `USER_EVENTS` | User mới → hr tạo hồ sơ HR mặc định |
| `user.updated` | user-service | hr-service | `USER_EVENTS` | Đổi department / role → hr cập nhật |
| `user.deactivated` | user-service | hr-service | `USER_EVENTS` | Vô hiệu hóa → hr đánh dấu nghỉ việc |

Payload (theo convention metadata sẵn có — `event_id`, `event_version`, `occurred_at` ở top-level):
```json
{
  "event_id": "uuid",
  "event_version": 1,
  "occurred_at": "2026-06-12T09:15:30Z",
  "user_id": "4f44e7f7-....",
  "email": "admin@company.com",
  "role": "admin",
  "department": "HR",
  "account_type": "internal",
  "is_active": true
}
```
Idempotency key: `event_id`; fallback `user_id + "user.created"`.

> Bổ trợ, KHÔNG thay thế: `hr.employee_profile.updated` (HR → Query Service) đã có vẫn giữ nguyên — nó cho chiều ngược (HR đổi hồ sơ → query cập nhật ACL). Hai chiều không xung đột.

### 2.3. Phía user-service (producer)

- Cần một **đường tạo user** (hiện chỉ có login/refresh/list/set-active — CHƯA có create). Khi thêm use case tạo user / hoặc tại điểm seed admin → publish `user.created`.
- Publish theo pattern publisher đã có ở các service khác (NATS JetStream, thêm metadata).
- `set_user_active_use_case` đổi trạng thái → publish `user.deactivated` / `user.updated`.
- **Best-effort, KHÔNG fail-closed**: publish lỗi không được làm hỏng việc tạo user (log + để backfill/lazy lo).

### 2.4. Phía hr-service (consumer)

- Thêm subscriber NATS (durable consumer, vd `HR_USER_LIFECYCLE`) cho `user.*`.
- `user.created` → **upsert idempotent** hồ sơ mặc định: tạo `leave_balance` (12 ngày phép, 10 ngày ốm mặc định theo server_default migration), tạo `employees` row (department/email từ payload). `ON CONFLICT DO NOTHING`.
- `user.updated` → cập nhật department/email.
- `user.deactivated` → set `employment_status='inactive'`.
- hr hiện chỉ có `NatsPublisher` rỗng (`src/hr-service/app/infrastructure/nats_publisher.py`) — cần thêm subscriber thật + wiring vào lifespan.

### 2.5. Lấp dữ liệu cũ (admin hiện tại) — KHÔNG vá tay

Event chỉ áp cho user TẠO SAU khi có cơ chế. User cũ (admin) cần một trong hai (khuyến nghị làm CẢ hai cho chắc):

1. **One-shot backfill**: lệnh ở user-service replay `user.created` cho toàn bộ user đang có → hr nuốt, tạo hồ sơ. Chạy 1 lần lúc go-live.
2. **Lazy safety-net trong hr** (khuyến nghị): khi nhận `hr_query` mà user chưa có record → **tự tạo record mặc định idempotent** rồi trả lời bình thường. Đây KHÔNG phải vá tay — nó tự động, idempotent, tự lành kể cả event miss.

→ Kết quả cuối: thêm người ở user-service → hr tự có hồ sơ; admin cũ → backfill/lazy tự lấp. **Không bao giờ seed tay nữa.** Migration `0001` của hr có thể bỏ phần seed 2 user hư cấu (hoặc giữ làm fixture test, KHÔNG dựa vào ở prod).

### 2.6. Test bắt buộc
- Unit hr: nhận `user.created` → tạo đúng hồ sơ; nhận lại y hệt → không nhân đôi (idempotent).
- Unit hr: lazy auto-create khi `hr_query` user chưa có → tạo + trả data, không 404.
- Integration (Docker, như `rag-langfuse`/e2e hr): publish `user.created` thật → query hr ra data.
- user-service: tạo/deactivate user → publish đúng subject + payload đủ field.

---

## 3. Thứ tự thực hiện (ít rủi ro → nhiều)

1. **document-service → Alembic** (Phần 1.2) — sạch nhất, ít data phức tạp. *Độc lập.*
2. **user-service → Alembic** (Phần 1.3 + bẫy 1.4) — cẩn thận `stamp` baseline trên VM. *Độc lập.*
3. **hr lazy auto-create** (Phần 2.5 mục 2) — lấp bug 404 NGAY, không chờ event. *Độc lập.*
4. **Event `user.*`** (Phần 2.2–2.4) + cập nhật subjects.md (xin duyệt Backend Dev) + backfill. *Phần lớn nhất, làm sau.*

Bước 1–3 làm song song được. Bước 4 phụ thuộc duyệt hợp đồng.

---

## 4. Definition of Done cho cả gói

Theo [04-definition-of-done.md](04-definition-of-done.md), cộng thêm:
- [ ] Cả 4 service dùng Alembic, mỗi service có `*-migrate` one-shot trong compose.
- [ ] DB mới `alembic upgrade head` PASS; VM đã `stamp` baseline an toàn (có backup trước).
- [ ] Bỏ runner tự chế user-service + file `.sql` cũ 2 service.
- [ ] subjects.md đã thêm `user.*` và được Backend Dev duyệt.
- [ ] Tạo user mới ở user-service → hr tự có hồ sơ (verify trên VM).
- [ ] Hỏi "số ngày phép còn lại của tôi" với admin thật → ra số thật, KHÔNG NO_INFO/404.
- [ ] Mọi consumer idempotent (test chứng minh nhận trùng không nhân đôi).
- [ ] Backward-compatible; event publish best-effort, KHÔNG fail-closed.

## 5. Liên kết
- Roadmap: [00-roadmap.md](00-roadmap.md) · DoD: [04-definition-of-done.md](04-definition-of-done.md) · Dev guide: [dev.md](dev.md)
- Hợp đồng event: [../../infra/nats/subjects.md](../../infra/nats/subjects.md)
- Mẫu Alembic chuẩn: [../../src/hr-service/migrations/env.py](../../src/hr-service/migrations/env.py) · [../../docker-compose.yml](../../docker-compose.yml) (block `hr-migrate`)
</content>
</invoke>
