# Plan — Orchestrator stream prose liên tục (hết flash JSON)

> Cho GPT 5.5 implement. Skills: Superpowers (đã brainstorm), design-taste-frontend, ui-ux-pro-max.

## Context

Trong timeline suy nghĩ LIVE (`Pipeline.vue`, mốc **Orchestrator** — "Agent đang xử lý"),
reasoning của orchestrator **lâu lâu lóe JSON thô rồi nảy về text gọn**. Nguyên nhân: orchestrator
hiện đang bị **gate** bằng `firstJsonObjectClosed(text)` rồi render qua `summarizeThought` (JSON →
section "Lý do / Các bước"). Gate này khớp **cặp ngoặc ĐẦU TIÊN** trong text — nên một ngoặc lạc
trong prose đang stream (vd `[1]`, `{x}`) làm gate mở SỚM, `summarizeThought` render cấu trúc
sai/JSON-ish, rồi khi JSON kế hoạch thật đóng lại render lại → **flash**.

User đã chốt: vị trí = khung Orchestrator của `Pipeline.vue`; mong muốn = **stream prose liên tục
token-by-token, ẩn hẳn JSON**; các bước plan vẫn hiện ở lane riêng như cũ.

Outcome: orchestrator đọc như model "nghĩ thành lời" mượt mà, không bao giờ thấy JSON, không nhảy
format. Chỉ đụng **đường LIVE** — `MessageSteps.vue` (bản persisted, đã gập trong toggle "Xem suy
nghĩ của agent") giữ nguyên `summarizeThought` nên không phát sinh flash lúc stream→done.

## Thay đổi

### 1. `src/frontend/chat/app/lib/timeline.ts`
- **Export** helper prose-sạch dùng cho LIVE — TÁI DÙNG `cleanNaturalLanguage` (timeline.ts:262,
  hiện private) vốn đã: bóc mọi khối JSON hợp lệ + **cắt khối JSON-like dở ở đuôi** (lúc đang
  stream) + bỏ "Output JSON" + recap kỹ thuật. Thêm wrapper null-guard:
  ```ts
  export function liveThoughtProse(text?: string | null): string {
    return cleanNaturalLanguage((text ?? '').trim())
  }
  ```
  Vì `stripJsonLikeBlocks` cắt phần `{"route":…` chưa đóng ở đuôi → trong lúc JSON stream, prose
  dẫn đầu hiện và lớn dần ổn định; JSON đóng xong thì bị bóc hẳn → **không bao giờ lộ JSON**.
- **Xóa** `firstJsonObjectClosed` (export ở dòng 219) — sau thay đổi chỉ Pipeline dùng nó, mà ta
  bỏ gate. `firstJsonStart`/`matchJsonEnd` GIỮ (còn phục vụ `extractFirstJsonObject`). Không test
  nào tham chiếu `firstJsonObjectClosed` → xóa an toàn.

### 2. `src/frontend/chat/app/components/chat/Pipeline.vue`
- Bỏ import `firstJsonObjectClosed`; thêm `liveThoughtProse`. Bỏ `orchReady` + `orchViews`
  (summarizeThought cho orchestrator) + comment "CHỐNG FLASH" cũ.
- Thêm:
  ```ts
  // Stream prose orchestrator liên tục, JSON luôn bị lọc bỏ (steps hiện ở lane plan bên dưới).
  // ponytail: nếu BE nhét reasoning HẲN trong JSON (không prose dẫn đầu) -> live hiện hint tới khi
  // có plan step; chấp nhận được, không lóe JSON.
  const orchProse = computed(() =>
    (orchThoughts.value.map(t => liveThoughtProse(t.text)).filter(Boolean).join('\n')).trim(),
  )
  ```
- Template mốc ORCHESTRATOR:
  - Đổi `v-if` block (hiện `orchReady.length || …`) → `v-if="orchProse || plan?.steps?.length || (isThinking && traceLog.length === 0)"`.
  - Thay `<ThoughtDetail v-for="(view,i) in orchViews">` bằng **1 đoạn prose chảy liên tục**:
    ```html
    <p v-if="orchProse"
       class="mt-1.5 max-w-[68ch] whitespace-pre-wrap break-words text-sm font-normal leading-relaxed text-slate-500 dark:text-muted-foreground">
      {{ orchProse }}
    </p>
    ```
  - Hint: đổi điều kiện `!orchReady.length` → `!orchProse`.
- Verify/other thoughts GIỮ NGUYÊN (vẫn `summarizeThought` + `ThoughtDetail`). `ThoughtDetail`
  import vẫn cần cho verify/other.

### UX (design-taste-frontend, ui-ux-pro-max)
- Dùng đúng typography reasoning sẵn có: `text-sm text-slate-500/dark:text-muted-foreground
  leading-relaxed max-w-[68ch] whitespace-pre-wrap` — đồng nhất với verify/other, không lệch tông.
- KHÔNG thêm fade/transition trên đoạn prose (text lớn dần là đủ mượt; transition gây giật). Shimmer
  giữ nguyên ở nhãn "Orchestrator" khi `orchActive`. Không đổi layout/rail → không nhảy.
- `whitespace-pre-wrap` để xuống dòng tự nhiên; `break-words` chống tràn ngang.

## Files
- `src/frontend/chat/app/lib/timeline.ts` (export `liveThoughtProse`, xóa `firstJsonObjectClosed`)
- `src/frontend/chat/app/components/chat/Pipeline.vue` (bỏ gate, render prose liên tục)
- `src/frontend/chat/tests/timeline-summary.test.ts` (thêm test `liveThoughtProse`)

## Verification
- **Unit** (`npm test` trong `src/frontend/chat`, dùng `node --test`): thêm vào
  `tests/timeline-summary.test.ts`:
  - prose thường → trả nguyên văn: `liveThoughtProse('Đang tra cứu chính sách nghỉ phép')` không đổi.
  - JSON dở ở đuôi (đang stream) → **không** chứa `{` / `"route"`:
    `liveThoughtProse('Phân tích yêu cầu {"route":"hea')` === `'Phân tích yêu cầu'`.
  - JSON đầy đủ lẫn prose → chỉ còn prose:
    `liveThoughtProse('Tôi sẽ tra cứu. {"route":"heavy","steps":[{"id":1,"role":"rag_retrieve"}]}')`
    không chứa `route`/`steps`/`{`.
  - rỗng/null → `''`.
  - (tùy chọn) guard ở `tests/streaming-no-flash.test.ts`: `Pipeline.vue` KHÔNG còn
    `firstJsonObjectClosed` và CÓ `liveThoughtProse`.
- **Manual**: chạy chat (`npm run dev`), hỏi câu kích heavy route (cần orchestrator + plan nhiều
  step). Quan sát khung "Agent đang xử lý → Orchestrator": prose chạy mượt token-by-token, **không
  hề thấy JSON**, các bước plan xuất hiện ở lane dưới như cũ; lúc xong gập gọn vào toggle, không giật.

## Không làm (out of scope)
- Không đụng `MessageSteps.vue` (persisted) — vẫn summary cấu trúc, đã gập trong toggle.
- Không đổi backend/SSE. Không đụng AnswerBlock (câu trả lời chính).
