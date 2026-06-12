# CHỈ THỊ THI CÔNG — Hoàn thiện đồng bộ data giữa các service

**Cập nhật:** 2026-06-12 · Chốt bởi: Nguyen Tran
**Đối tượng:** dev backend làm `user-service`, `hr-service`.
**Tính chất:** Đây là **chỉ thị đã chốt** — KHÔNG bàn lại phương án. Làm đúng chỗ ghi, đúng cách ghi, test đúng case ghi. Xong → đưa review → đưa vào CI/CD.

> **ĐỌC BẮT BUỘC 1 LẦN:** [05-db-migration-va-dong-bo.md](05-db-migration-va-dong-bo.md) (kiến trúc đã có) + [infra/nats/subjects.md](../../infra/nats/subjects.md) (hợp đồng event). Đổi payload/subject phải báo Backend Dev trước.

## QUY TẮC CỨNG (vi phạm = trả lại PR)
1. KHÔNG đọc DB service khác. Đồng bộ CHỈ qua event NATS / HTTP nội bộ.
2. Consumer **idempotent** (dedupe `event_id`, dùng `ON CONFLICT`). Producer **best-effort** (lỗi publish chỉ log warning, KHÔNG raise, KHÔNG chặn nghiệp vụ).
3. Payload theo subjects.md (business fields top-level + `event_id`/`event_version`/`occurred_at`). DÙNG LẠI helper `build_*` có sẵn, KHÔNG tự ghép tay.
4. Test fail-fast: dùng fake/stub, **KHÔNG NATS thật, KHÔNG sleep**. Test phải nổ lỗi ngay, không nuốt log.
5. Branch từ `nguyendev`, mỗi task 1 PR → `develop`.

## QUYẾT ĐỊNH KIẾN TRÚC ĐÃ CHỐT (không đổi nếu chưa hỏi Nguyen)
- **`department` source-of-truth = user-service.** hr_db chỉ giữ BẢN SAO đọc từ event `user.*`. **hr KHÔNG được tự sửa department.** Khi hr publish `hr.employee_profile.updated`, field `department` = giá trị hr nhận từ `user.*` (chuyển tiếp, không tự chế).
- **Lazy auto-create giữ nguyên: CHỈ tạo `leave_balance`.** KHÔNG tạo `employees` ở đường lazy (hiện không intent nào đọc `employees`). `employees` chỉ tạo qua event/backfill.
- **Forward-sync user→hr dùng backfill one-shot tự động** (KHÔNG cần API tạo user). Idempotent, chạy mỗi deploy.

---

# TASK 1 — Tự động phát `user.created` cho mọi user (user-service)

### Vấn đề
Subscriber hr đã xong, publisher đã có, NHƯNG `user.created` chưa bao giờ tự bắn (user seed tay, không có luồng tạo user gọi `repo.create`). → user mới hr không biết tới khi user hỏi (lazy).

### Làm Ở ĐÂU + LÀM GÌ
1. **Thêm service `user-backfill` (one-shot) vào [docker-compose.yml](../../docker-compose.yml)** — đặt NGAY SAU block `user-migrate`:
   ```yaml
   user-backfill:
     image: ${DOCKERHUB_USERNAME:-CHANGE_ME}/user-service:${IMAGE_TAG:-develop}
     command: ["python", "scripts/backfill_user_events.py"]
     working_dir: /app
     env_file:
       - ./deploy/env/common.env
       - ./deploy/env/user-service.env
     depends_on:
       user-migrate:
         condition: service_completed_successfully
       nats-bootstrap:
         condition: service_completed_successfully
     restart: "no"
   ```
   Script đã có: [src/user-service/scripts/backfill_user_events.py](../../src/user-service/scripts/backfill_user_events.py). Nó replay `user.created` cho TẤT CẢ user (idempotent — hr `ON CONFLICT DO NOTHING`).
2. **Thêm `user-backfill` tương tự vào [docker-compose.e2e.yml](../../docker-compose.e2e.yml)** (sau `seed-user`, `depends_on seed-user + nats-bootstrap completed`) để e2e cũng chạy luồng này.
3. **KHÔNG** sửa publisher/emitter (đã đúng). **KHÔNG** thêm API tạo user.

### Contract
- subjects.md `user.created`: required `event_id, event_version, occurred_at, user_id, email, role, department, account_type, is_active`. `build_user_event()` trong [user_event_publisher.py](../../src/user-service/app/infrastructure/messaging/user_event_publisher.py) đã đúng — DÙNG LẠI.
- Stream `USER_EVENTS` đã provision ([bootstrap_streams.py](../../infra/nats/bootstrap_streams.py)).

### TEST BẮT BUỘC (thêm vào [src/user-service/tests/test_user_events.py](../../src/user-service/tests/test_user_events.py))
- `backfill` với fake publisher + 3 user giả → gọi `publish_user_event("user.created", ...)` đúng 3 lần, payload đủ field.
- Publisher raise giữa chừng → script KHÔNG nuốt: thoát non-zero (fail-fast). (Test bằng cách monkeypatch publisher ném lỗi, assert SystemExit/exit code != 0.)
- (hr side đã có sẵn) bảo đảm [test_user_events_handler.py](../../src/hr-service/tests/test_user_events_handler.py) còn xanh: nhận `user.created` → tạo `employees` + `leave_balance`; nhận TRÙNG → không nhân đôi (thêm case trùng nếu chưa có).

### DONE khi
Deploy → log `user-backfill` báo "đã phát user.created cho N user"; hỏi HR cho user bất kỳ ra số thật không cần lazy; e2e xanh.

---

# TASK 2 — hr PHẢI publish `hr.employee_profile.updated` (hr → query)

### Vấn đề (đã xác minh)
query-service ĐÃ có consumer `handle_hr_employee_profile_updated` + projection `query_svc.user_access_profile` ([nats_events.py](../../src/query-service/app/infrastructure/messaging/nats_events.py), [postgres_user_access_profile_repo.py](../../src/query-service/app/infrastructure/db/postgres_user_access_profile_repo.py)). NHƯNG hr [nats_publisher.py](../../src/hr-service/app/infrastructure/nats_publisher.py) là **STUB no-op** và `publish_profile_updated` không ai gọi → projection KHÔNG bao giờ cập nhật → ACL theo phòng ban sai/rỗng.

### Làm Ở ĐÂU + LÀM GÌ
1. **Implement `NatsPublisher` thật** trong [src/hr-service/app/infrastructure/nats_publisher.py](../../src/hr-service/app/infrastructure/nats_publisher.py) — **mirror** [src/document-service/app/infrastructure/messaging/nats_publisher.py](../../src/document-service/app/infrastructure/messaging/nats_publisher.py): connect lazy, JetStream `ensure stream HR_EVENTS`, thêm metadata, best-effort. Dùng `settings.nats_url` + `settings.nats_jetstream_enabled` (đã có trong [hr config](../../src/hr-service/app/core/config.py)).
2. **Gọi publish khi `employees` thay đổi:** trong [postgres_hr_repository.py](../../src/hr-service/app/infrastructure/db/postgres_hr_repository.py)::`upsert_employee_from_user`, SAU khi commit thành công → publish `hr.employee_profile.updated`. Vì repo không nên giữ publisher, làm theo 1 trong 2 (chọn cách đơn giản, ghi rõ trong PR):
   - Trả về dict thông tin vừa upsert cho caller (subscriber handler) rồi handler publish; HOẶC
   - Inject publisher vào handler [user_events_subscriber.py](../../src/hr-service/app/infrastructure/user_events_subscriber.py)::`handle_user_event`: sau `upsert_employee_from_user` → `publisher.publish_profile_updated(payload)`.
   → **Khuyến nghị: publish ở `handle_user_event`** (giữ repo thuần DB).
3. Payload `hr.employee_profile.updated`: `user_id, account_type, department, employment_status` (+ metadata). `department` = giá trị nhận từ `user.*` (theo quyết định source-of-truth).
4. Wiring publisher vào lifespan/handler hr ([main.py](../../src/hr-service/app/main.py)) — tạo 1 publisher dùng chung, truyền vào subscriber.

### CHỐNG LOOP (bắt buộc)
Luồng: `user.* → hr provision → hr.employee_profile.updated → query`. **hr KHÔNG được nghe lại event của chính nó.** Chỉ query nghe `hr.employee_profile.updated`. Idempotent + `occurred_at` mới nhất thắng (repo query đã xử lý: `WHERE updated_at <= EXCLUDED.updated_at`).

### Contract
subjects.md `hr.employee_profile.updated`: Producer HR → Consumer Query, stream `HR_EVENTS`, required `event_id, event_version, occurred_at, user_id, account_type, department, employment_status`.

### TEST BẮT BUỘC
- hr: sau `handle_user_event(user.created)` → publisher nhận đúng `hr.employee_profile.updated` với payload đủ field (fake publisher ghi lại subject+payload).
- hr: publisher ném lỗi → `handle_user_event` vẫn xong (best-effort, không raise) — nhưng KHÔNG ack nếu phần ghi DB lỗi (giữ retry). Tách rõ: lỗi DB → nak; lỗi publish → nuốt + log.
- hr: KHÔNG có consumer nào của hr subscribe `hr.employee_profile.updated` (chống loop) — assert subscriber chỉ đăng ký `user.*`.

### DONE khi
Tạo/đổi user → query_svc.user_access_profile có/đổi row tương ứng (verify VM); hr không loop; CI xanh.

---

# TASK 3 — (ƯU TIÊN THẤP) Đối soát định kỳ
Đã thêm recipe vận hành để chạy [backfill_user_events.py](../../src/user-service/scripts/backfill_user_events.py) theo cron mà **KHÔNG đọc DB service khác**:

- Wrapper chạy tay/cron: [deploy/scripts/run_user_backfill.sh](../../deploy/scripts/run_user_backfill.sh)
- Script cài `crontab` idempotent trên VM: [deploy/scripts/install_user_backfill_cron.sh](../../deploy/scripts/install_user_backfill_cron.sh)

Nguyên tắc:
- Cron chỉ gọi lại service `user-backfill` đã có sẵn qua `docker compose run --rm --no-deps user-backfill`.
- Có `flock` để chống chạy chồng nếu job cũ chưa xong.
- Log mỗi lần chạy ghi vào `.tmp/user-backfill/*.log`.
- Idempotency vẫn dựa trên consumer HR (`ON CONFLICT` + upsert), nên chạy lại không nhân đôi dữ liệu.

Lệnh cài trên VM:

```bash
cd ~/DA08-VSF
bash deploy/scripts/install_user_backfill_cron.sh
```

Đổi lịch:

```bash
cd ~/DA08-VSF
CRON_SCHEDULE="0 */6 * * *" bash deploy/scripts/install_user_backfill_cron.sh
```

---

## THỨ TỰ LÀM
1. **TASK 1** trước (độc lập, rủi ro thấp, đóng luồng user→hr cho user mới).
2. **TASK 2** sau (cần cẩn thận chống loop).
3. **TASK 3** khi cần đối soát định kỳ thì cài cron bằng script ở trên, không cần mở thêm API hay đọc chéo DB.

## DoD MỖI PR (tick đủ mới merge)
- [ ] Đúng file/đúng cách theo chỉ thị trên.
- [ ] Consumer idempotent (test nhận trùng), producer best-effort (test lỗi publish không vỡ).
- [ ] subjects.md cập nhật nếu đụng contract (không đụng nếu làm đúng payload sẵn có).
- [ ] Unit fail-fast bằng fake, KHÔNG NATS thật/sleep. CI unit + e2e xanh.
- [ ] Verify VM: user mới → hr có hồ sơ; (Task 2) → query projection cập nhật.

## Liên kết
[05-db-migration-va-dong-bo.md](05-db-migration-va-dong-bo.md) · [infra/nats/subjects.md](../../infra/nats/subjects.md) · [dev.md](dev.md) · [04-definition-of-done.md](04-definition-of-done.md)
