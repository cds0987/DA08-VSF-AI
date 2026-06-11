# GAP — rag-worker: `_ensure()` latch `_ready` → ingest chết khi collection biến mất giữa chừng

Scope: `src/rag-worker` — Qdrant **write path** (`QdrantRemoteProvider._ensure` + insert/upsert).
Grounding: sự cố THẬT trên `e2e-cloud` run `27129674584` attempt 1 (2026-06-08), endpoint Qdrant
VM dùng chung `34.87.176.141`. Đọc log rag-worker + `core_engine/vectorstore/providers/qdrant/remote.py`.
Status: **RESOLVED** (2026-06-11) — G-E1 + G-E2 đã code + test (commit `409a38a` "Recover
Qdrant writes after missing collection"). G-E3 (CI isolation) coi như đủ nhờ self-heal +
cleanup e2e-cloud sẵn có — để lại như defense-in-depth tùy chọn.

> Quy ước: `OPEN` = đã xác minh trong code/log hiện tại, chưa có implementation.
> `RESOLVED` = đã có implementation + test xác minh.

## ✅ Resolution (2026-06-11)
- **G-E1** — [`providers/qdrant/remote.py`](../../core_engine/vectorstore/providers/qdrant/remote.py): thêm `_retry_on_missing_collection(op)` bắt `is_qdrant_collection_missing_error` → reset `_ready=False` → `_ensure()` (tạo lại collection + payload index) → retry op MỘT lần. Wrap mọi op (insert/upsert/list/delete). Giữ cache `_ready` cho happy path.
- **G-E2** — `ingest_document_use_case.classify_ingest_error`: `is_qdrant_collection_missing_error` → `transient` (job retry thay vì FAILED-cứng).
- **Test** — `tests/core_engine/test_qdrant_remote_behavior.py`: `..._recreates_collection_and_retries_once` (tạo lại + retry) + `..._raises_when_collection_missing_after_retry` (404 lần 2 vẫn raise, không loop vô hạn). 4 passed.
- **Còn lại (tùy chọn):** `inprocess.py` vẫn latch `_ready` một chiều — KHÔNG fix vì Qdrant embedded không thể mất collection từ bên ngoài. G-E3 (Qdrant ephemeral cho CI) chưa làm; self-heal đã khử lỗi 404-vĩnh-viễn nên không còn cấp thiết.

---

## 1. Sự cố (bằng chứng thật)

`e2e-cloud` attempt 1 fail ở step *Verify ingest*: **0/9 doc có vector** sau 360s. Mọi ingest job báo:

```
ingest_job_failed  error_class=permanent  error_type=UnexpectedResponse
  "Unexpected Response: 404 (Not Found) ... Collection `rag_chatbot__te3s__d1536` doesn't exist!"
```

Timeline từ log (cùng 1 collection data):

| Thời điểm | Sự kiện | Kết quả |
|----------|---------|---------|
| 09:53:44 | stamp write `__meta` | 200 ✅ (connect OK) |
| 09:53:45 | `GET .../rag_chatbot__te3s__d1536/exists` + `scroll` | **200** — collection TỒN TẠI (leftover) |
| 09:53:56 | `scroll` cùng collection | **404** — collection ĐÃ BIẾN MẤT |
| 09:53:56 → 09:59:46 | mọi upsert/scroll | **404** liên tục, 0 doc ghi được |

Đặc điểm chốt: **KHÔNG có lệnh `PUT /collections/rag_chatbot__te3s__d1536` (create)** trong toàn log
→ provider chưa từng tạo collection; nó dựa vào bản leftover, rồi bản đó bị xoá từ bên ngoài.

> `/readyz`, stamp write, embedding OpenAI đều 200 → **lớp connect/timeout KHÔNG phải nguyên nhân**.

## 2. Root cause — `_ensure()` latch một chiều

[`providers/qdrant/remote.py:30` `_ensure()`](../../core_engine/vectorstore/providers/qdrant/remote.py#L30):

```python
async def _ensure(self) -> None:
    if self._ready:            # latch: lần sau bỏ qua hoàn toàn
        return
    async with self._lock:
        if self._ready:
            return
        if not await self._client.collection_exists(self._collection):
            await self._client.create_collection(...)
            await self._client.create_payload_index(...)
        self._ready = True      # set 1 lần, KHÔNG bao giờ reset
```

Lỗi: `_ensure` chỉ chạy "thật" **một lần**. Khi khởi động thấy `collection_exists=True` (leftover) →
**bỏ qua create** → `_ready=True`. Nếu collection sau đó **biến mất** (bị xoá ngoài, Qdrant restart mất
data, ops drop nhầm), provider **không bao giờ tạo lại** → mọi write 404 vĩnh viễn.

Khuếch đại: 404 này bị phân loại `error_class=permanent` → job `FAILED` không retry → corpus chết sạch.

## 3. Vì sao xảy ra thật (không phải lý thuyết)

- Qdrant `34.87.176.141` là **VM dùng chung, persistent** — dev/test khác ghi/xoá collection bất kỳ lúc nào.
- Leftover state từ phiên test trước + một thao tác xoá giữa chừng = đủ trigger. Re-run (state sạch) thì
  `_ensure` tạo mới → pass; nên lỗi **flaky theo state bên ngoài**, không deterministic.
- Cùng họ rủi ro với gap8 (độ bền write path) nhưng là một lỗ KHÁC: **không tự phục hồi khi collection mất**.

## 4. Đề xuất fix (CHỐT hướng)

### 4.1 Tự phục hồi khi collection mất (chính)
Trong write op (`insert_many`/`upsert_many`/`delete_*`), bắt riêng lỗi *collection-not-found* (404
`UnexpectedResponse`) → **reset `_ready=False`, gọi lại `_ensure()` (tạo lại), retry op một lần**:

```python
async def _with_collection(self, op):
    try:
        return await op()
    except UnexpectedResponse as e:
        if e.status_code == 404 and "doesn't exist" in str(e.content):
            self._ready = False
            await self._ensure()     # tạo lại collection + payload index
            return await op()        # retry đúng MỘT lần
        raise
```

- Idempotent: nếu collection thật sự không tạo được → lỗi lần 2 nổi lên như cũ.
- Giữ `_ready` cache cho happy path (không bỏ tối ưu).

### 4.2 Phân loại lỗi đúng (phụ)
*collection-not-found sau khi đã ensure* là **transient/retryable**, không phải `permanent`. Sửa
classification ở `ingest_document_use_case` để job được retry thay vì FAILED-cứng (đồng bộ tinh thần gap8 G8-1/G8-2).

### 4.3 Cô lập hạ tầng CI (phòng tuyến 2)
`e2e-cloud` nên trỏ Qdrant **riêng/ephemeral** cho CI (không ai ngoài ghi), HOẶC bước seed **wipe + create
tường minh** collection trước khi ingest. Tránh phụ thuộc state VM dùng chung.

## 5. Test plan
- **Unit** (mock client): collection_exists=True → ensure skip create; mô phỏng write raise 404
  not-found → assert provider **reset `_ready` + gọi create_collection + retry** thành công.
- **Unit**: 404 not-found lần 2 vẫn raise (không loop vô hạn).
- **Integration** (Qdrant thật): tạo collection, xoá ngoài, gọi upsert → vẫn ghi được (đã tự tạo lại).

## 6. Ràng buộc / phối hợp
- File `qdrant/remote.py` đang được **gap8 (G8-5/G8-6)** sửa (scroll phân trang, batch upsert) →
  **nối đuôi, đừng song song** (tránh đụng độ/rebase — xem bài học commit nhân đôi PR #38).
- Giữ behavior happy-path: collection có sẵn + còn sống → không đổi số request (vẫn cache `_ready`).
- Áp pattern tương tự cho `qdrant/inprocess.py` nếu có cùng latch.

## 7. Tóm tắt
| ID | Mức | Vấn đề | File | Trạng thái |
|----|-----|--------|------|------------|
| G-E1 | Cao | `_ensure` latch `_ready`, không tạo lại khi collection mất → ingest 404 vĩnh viễn | `providers/qdrant/remote.py` | ✅ RESOLVED (409a38a) + test |
| G-E2 | Trung bình | 404 collection-not-found bị phân loại `permanent` → job không retry | `ingest_document_use_case` | ✅ RESOLVED (→ transient) |
| G-E3 | Trung bình | CI phụ thuộc Qdrant VM dùng chung (state bên ngoài) → flaky | `e2e-cloud.yml` / `ci_e2e.py` | 🟢 Tùy chọn — đã giảm nhờ self-heal + cleanup |
