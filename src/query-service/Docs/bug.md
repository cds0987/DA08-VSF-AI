# Bug & Feature Requests — Frontend (từ query-service team)

## Trạng thái hiện tại (2026-06-12)

query-service đã hoàn thành các sửa đổi phía backend liên quan đến 3 vấn đề UX chat.
Phần còn lại cần đội FE hoàn thiện.

---

## [DONE — backend] #1: Click tài liệu trong citation không hiển thị

**Gốc nguyên nhân (đã xác minh):**
- `SourcePanel.vue` trước đây gọi `documentService.getFileUrl(...)` — method không tồn tại → lỗi runtime. → **FE develop đã tự sửa** (gọi đúng `getDocumentFile`).
- `chat.ts` trước đây không có `document_id` trong `QuerySource` map. → **FE develop đã sửa** bằng `sourceDocumentId()` tự suy từ `source_gcs_uri` (parse `/raw/<id>/`).

**Backend fix (query-service, commit 2026-06-12):**
- `SourceDoc` (langgraph_state.py) và `_source_payload` (orchestration.py) **giờ gửi tường minh** `document_id` và `page_number` trong SSE `done.sources[*]`.
- FE nhận `document_id` trực tiếp, không cần parse URI (fallback parse URI vẫn hoạt động nếu backend cũ).
- Nếu click tài liệu vẫn không hiện gì sau khi FE cập nhật map `document_id` → kiểm tra endpoint resolve file (`getDocumentFile`) phía FE/document-service trả về URL đúng chưa — đây không phải vấn đề của query-service.

**Schema `sources[*]` sau backend fix (LangGraph path):**
```json
{
  "document_name": "string",
  "caption": "string",
  "heading_path": ["string"],
  "score": 0.5,
  "source_gcs_uri": "gs://...",
  "document_id": "uuid-string",
  "page_number": 3
}
```

**Trạng thái:** FE nên dùng `document_id` trực tiếp (bỏ / giữ fallback parse URI cho backward-compat).

---

## [DONE — backend] #2: Streaming "giả" — câu trả lời trả về 1 lần

**Gốc nguyên nhân (đã xác minh):**
- `OpenAIResponsesChatModel` thiếu `_astream` → `astream_events(v2)` không phát `on_chat_model_stream` → câu trả lời sinh trọn rồi cắt giả bằng `_word_chunks`.

**Backend fix (query-service, commit trước):**
- Thêm `_astream` async vào adapter → token đến từng chút trong khi LLM sinh.
- Nhánh `force_answer` trong `think_node` chuyển sang `astream` thay vì `ainvoke`.
- `_word_chunks` giữ làm fallback (chỉ chạy khi `answer_accumulator` rỗng).

**Trạng thái:** FE (`chat.ts`) đã sẵn sàng tiêu thụ `QueryTokenEvent {token, phase}` → không cần đổi FE.

---

## [DONE — backend, cần FE hoàn thiện] #3: Show thinking — reasoning timeline chi tiết

### Đã làm ở backend (query-service, commit trước)

query-service phát event `{token: "", phase: "<phase>"}` tại mỗi node:
- `triage` / `think` → `phase: "thinking"`
- `act` → `phase: "acting"`
- `observe` → `phase: "observing"`
- `answer` → `phase: "generating"`

FE `chat.ts` đã có `PHASE_MAP` cập nhật `pipeline.value` từ `payload.phase` ngay cả khi `token === ""`
(`isTokenEvent` chấp nhận `token: ""`).
→ **`Pipeline.vue` 4-stage tự chạy động mà không cần sửa FE.**

### Cần FE làm thêm (reasoning timeline giàu thông tin)

Để hiển thị **timeline chi tiết** (tên tool đang gọi + danh sách tài liệu truy hồi được + score),
backend sẽ phát thêm event mới — nhưng FE cần hỗ trợ nhận và render.

**Schema event mới backend sẽ phát (sau khi FE ready):**

```ts
interface QueryStepEvent {
  phase: 'thinking' | 'acting' | 'observing' | 'generating'
  step: string          // nhãn tiếng Việt, ví dụ "Tìm thấy 3 tài liệu"
  tool?: string         // tên tool, ví dụ "rag_search" | "hr_query"
  docs?: Array<{
    document_name: string
    score: number
  }>
}
```

Event này **không có `token`** → `isTokenEvent` hiện bỏ qua nó. FE cần xử lý riêng.

**Việc FE cần làm:**

1. **`app/types/index.ts`** — thêm interface `QueryStepEvent` (xem schema trên).

2. **`app/stores/chat.ts`** — trong `onmessage` handler của `fetchEventSource`:
   - Thêm type guard `isStepEvent(payload)` kiểm tra `typeof payload.step === "string"`.
   - Khi nhận step-event: push vào mảng `reasoningSteps` của message đang build
     (hoặc một reactive ref tạm trong quá trình stream).
   - Lưu vào `ChatMessage` để render sau khi stream xong.
   - Cần thêm `reasoningSteps?: QueryStepEvent[]` vào `ChatMessage` type.

3. **`app/components/chat/Pipeline.vue`** (hoặc component mới `ReasoningTimeline.vue`) — render danh sách step-events:
   - Mỗi step hiển thị: icon phase + nhãn tiếng Việt + (nếu có `docs`) bảng tài liệu/score.
   - Có thể collapsible để không chiếm quá nhiều diện tích.

**Lưu ý implementation:**
- Khi backend bắt đầu phát step-events, `chat.ts` hiện tại bỏ qua (không crash) → có thể triển khai FE mà không block.
- `Pipeline.vue` hiện chỉ render 4-stage tĩnh (done/in-progress/pending) — cần mở rộng hoặc tách component.
- `isTokenEvent` hiện dùng `typeof (value as QueryTokenEvent).token === "string"` → step-event không có `token` sẽ bị bỏ qua đúng hành vi.

---

## [Ghi chú — rag-service] #4: Giới hạn top_k phía rag-service

query-service đã nới trần `top_k` lên 10 (từ 5) và mặc định `rag_top_k=8` (config).
Nếu rag-service chặn `top_k > 5` ở phía nó (validation, query limit) → **cần rag-service team nới trần tương tự** để tận dụng cải tiến retrieval. Kiểm tra bằng Langfuse span `rag_search`: so sánh `total` returned với `top_k` requested.

---

## Tóm tắt action items cho FE

| Vấn đề | Backend | FE cần làm |
|--------|---------|------------|
| #1 Click tài liệu | ✅ Đã gửi `document_id` + `page_number` tường minh (2026-06-12) | Dùng `document_id` trực tiếp; nếu vẫn lỗi → kiểm tra `getDocumentFile` endpoint |
| #2 Streaming thật | ✅ `_astream` + nhánh stream | Không cần — đã tiêu thụ đúng |
| #3 Reasoning timeline (cơ bản) | ✅ Phase-events → Pipeline.vue tự chạy | Không cần |
| #3 Reasoning timeline (chi tiết) | ⏳ Chờ FE ready để phát step-event | **Cần làm** (xem mục #3 trên) |
| #4 top_k > 5 | ✅ query-service nới lên 10 | rag-service team xác nhận giới hạn phía rag-service |
