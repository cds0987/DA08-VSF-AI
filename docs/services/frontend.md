---
service: frontend
path: src/frontend
last-verified: 889e9eab (2026-06-29)
code-refs:
  - src/frontend/chat/package.json
  - src/frontend/chat/nuxt.config.ts
  - src/frontend/chat/app/lib/api/axiosClient.ts
  - src/frontend/chat/app/lib/api/queryService.ts
  - src/frontend/chat/app/lib/api/authService.ts
  - src/frontend/chat/app/lib/api/documentService.ts
  - src/frontend/chat/app/lib/api/hrService.ts
  - src/frontend/chat/app/lib/documentViewer.ts
  - src/frontend/chat/app/stores/chat.ts
  - src/frontend/chat/app/stores/session.ts
  - src/frontend/chat/app/middleware/auth.global.ts
  - src/frontend/chat/app/types/sse-contract.gen.ts
  - src/frontend/chat/app/components/SourcePanel.vue
  - src/frontend/chat/app/components/chat/MessageSteps.vue
  - src/frontend/chat/app/components/chat/Pipeline.vue
---
# Frontend

## Trách nhiệm
Web UI cho người dùng cuối: chat hỏi-đáp RAG có nguồn (citation), tạo/duyệt đơn nghỉ, xem
lịch sử hội thoại, xem tài liệu gốc, thông báo. Mọi call đi qua API Gateway tới các
microservice (user/query/document/hr/mcp). Không gọi LLM/Qdrant trực tiếp.

## Stack & cấu trúc
- **Nuxt 4 + Vue 3** (compatibilityVersion 4), TypeScript, Pinia, TanStack Vue Query,
  Tailwind v4, reka-ui (shadcn-vue port), vee-validate+zod, vue-sonner.
- SSE qua `@microsoft/fetch-event-source`; markdown-it + dompurify; viewer tài liệu dùng
  officeparser / xlsx (SheetJS) / utif.
- **3 app Nuxt riêng** trong `src/frontend/` dùng chung pattern (app dir `app/`):
  - `chat/` — app chính người dùng (port 3000). **Trọng tâm tài liệu này.**
  - `admin/` — dashboard quản trị + upload/ingest tài liệu (port 3001, có Playwright e2e).
  - `base/` — khung tối giản (chỉ login/auth shell), làm nền chung.
- Thư mục `chat/app/`: `pages/` (routes), `components/` (`chat/`, `auth/`, `ui/`),
  `stores/` (Pinia: `chat`, `session`, `notifications`), `lib/api/` (HTTP clients),
  `lib/` (helper thuần: streamBuffer, documentViewer, quote, timeline…),
  `composables/`, `middleware/auth.global.ts`, `types/`.

## Màn hình / luồng chính
- **Routes** (`chat/app/pages/`): `login.vue`, `index.vue`, `chat/index.vue`,
  `chat/[id].vue` (1 hội thoại), `leave-approvals.vue` (duyệt đơn nghỉ).
- **Auth**: `auth.global.ts` middleware — lần đầu vào (client) gọi `session.fetchMe()`
  (`GET /auth/me`) để xác thực thật thay vì chỉ tin cookie; chưa đăng nhập → redirect
  `/login`. Đã login mà vào `/login` → về `/chat`.
- **Chat**: `pages/chat/index.vue` render `ChatMessages` + `ChatInput`; gọi
  `chatStore.ask()` → mở SSE tới `/query`. Hỗ trợ trích dẫn lại đoạn bot (quote → blockquote),
  đính kèm `document_ids`, retry khi stream đứt (giữ partial content).
- **Đơn nghỉ**: model trả PURE JSON action (`create_leave_request` /
  `review_leave_approvals`) trong stream → store tách JSON khỏi text (`extractAction`),
  dựng câu dẫn tiếng Việt + form xác nhận (`ActionableCard`/`ApprovalReviewCard`). Confirm
  ghi qua `useHRService` → `POST {query}/leave-requests` (đi qua query-service để inject
  user_id). `idempotency_key` TẤT ĐỊNH theo nội dung+user (cyrb53) → bền qua reload.
- **Xem tài liệu** (`SourcePanel.vue` + `lib/documentViewer.ts`): click citation → panel
  trượt; `documentService.getDocumentFile(id)` (`GET {document}/{id}/file`) trả presigned
  URL; FE fetch về blob same-origin cho PDF.js (tránh chặn cross-origin). Chế độ theo đuôi
  tệp: pdf / office(docx,pptx) / sheet(xlsx,xls,csv qua SheetJS) / markdown / html /
  text / image / tiff(UTIF→PNG) / fallback "Mở tài liệu gốc". HTML qua DOMPurify
  (FORBID script/iframe/object/embed).
- **Lịch sử**: load từ query-service (`/conversations`); cache localStorage làm fallback
  + lưu phần agent client-only (trace/thoughts/plan/models) khôi phục sau reload.

## Tích hợp SSE
`chatStore.ask()` POST `{gateway}{queryPath}/query` (mặc định `/api/query/query`), parse
mỗi `message.data` là JSON. Hai loại event (phân biệt bởi `done`):
- **token event** (`isTokenEvent`): các `phase` (hợp đồng `sse-contract.gen.ts`):
  - `token` → nối vào `streamingText` (qua streamBuffer + rafScheduler).
  - `model_used` → ghi model thật từng node (minh bạch vận hành).
  - `thought` → dòng suy luận, gộp liên tiếp cùng node.
  - `plan` (steps) → dựng lane subagent song song (pending/running/ok/error).
  - `step` → cập nhật trạng thái 1 node.
  - `acting`/`observing` (+`tool`) → trace log (tool gọi + kết quả tóm tắt).
  - `thinking`/`generating` → đổi pipeline stage.
- **done event** (`isDoneEvent`, BẮT BUỘC `done:true`+`session_id`+`sources[]`): chốt câu
  trả lời, dựng `citations` từ `sources`, lưu `trace_id`, `message_id`, `fallback`.
- **Render agent tree**: `MessageSteps.vue` (đã xong) / `Pipeline.vue` (live) gom `thought`
  theo `nodeGroup()` (groups: orchestrator→worker→verify→answer) — GENERIC theo hợp đồng,
  thêm node backend tự hiện đúng group. done-event thiếu field → `console.warn` (không treo câm).
- Hợp đồng 1 nguồn: `query-service/.../sse_contract.py` → gen `sse-contract.gen.ts` (CI gate diff).

## Config / ENV
`runtimeConfig.public` (`chat/nuxt.config.ts`), set qua biến `NUXT_PUBLIC_*`:
- `apiGatewayUrl` (base mọi call), `gatewayBasicAuth` (header `Authorization-Gateway`).
- Path prefix mỗi service: `userServicePath` (`/api/user`), `documentServicePath`
  (`/api/documents`), `queryServicePath` (`/api/query`), `hrServicePath` (`/api/hr`),
  `mcpServicePath` (`/api/mcp`).
- `adminAppUrl`, `chatAppUrl`, `appKind` (= `chat`).
- **axiosClient** (`lib/api/axiosClient.ts`): timeout 30s, gắn `X-Request-ID`, gắn
  `Authorization: Bearer <access cookie>`, auto-refresh 1 lần khi 401 rồi retry; refresh
  fail → logout. Token lưu cookie (`ACCESS_TOKEN_COOKIE`); user lưu cookie `SESSION_COOKIE`
  maxAge 30 ngày (khớp refresh TTL).

## Code map
- API base + auth refresh: [axiosClient.ts](src/frontend/chat/app/lib/api/axiosClient.ts)
- SSE + state chat: [stores/chat.ts](src/frontend/chat/app/stores/chat.ts)
- Hợp đồng SSE (gen): [sse-contract.gen.ts](src/frontend/chat/app/types/sse-contract.gen.ts)
- Query/notification/conversation client: [queryService.ts](src/frontend/chat/app/lib/api/queryService.ts)
- Auth: [authService.ts](src/frontend/chat/app/lib/api/authService.ts) · [session.ts](src/frontend/chat/app/stores/session.ts) · [auth.global.ts](src/frontend/chat/app/middleware/auth.global.ts)
- Đơn nghỉ: [hrService.ts](src/frontend/chat/app/lib/api/hrService.ts) · [leave-approvals.vue](src/frontend/chat/app/pages/leave-approvals.vue)
- Xem tài liệu: [documentViewer.ts](src/frontend/chat/app/lib/documentViewer.ts) · [SourcePanel.vue](src/frontend/chat/app/components/SourcePanel.vue) · [documentService.ts](src/frontend/chat/app/lib/api/documentService.ts)
- Agent tree render: [MessageSteps.vue](src/frontend/chat/app/components/chat/MessageSteps.vue) · [Pipeline.vue](src/frontend/chat/app/components/chat/Pipeline.vue)
- Trang chat: [chat/index.vue](src/frontend/chat/app/pages/chat/index.vue)
- Config: [nuxt.config.ts](src/frontend/chat/nuxt.config.ts)
