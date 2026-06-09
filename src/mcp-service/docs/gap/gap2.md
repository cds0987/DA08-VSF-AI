# Gap 2 — Tool `hr_query` (proxy mcp-service ↔ hr-service)

> Phạm vi: tool `hr_query` ở mcp-service ([app/tools/hr_query.py](../../app/tools/hr_query.py)) — HTTP proxy sang hr-service `POST /hr/query`.
> Đối chiếu với thiết kế [docs/maintool/hr_query.md](../maintool/hr_query.md) + code thật hai phía.
> Trạng thái tool: 🟢 đã chạy được 4 intent MVP (read-only); 🔴 thiếu phần phi-happy-path, bảo mật và độ phủ intent.
> Các runtime bug (lệch shape response, 404 làm vỡ chat...) **không** ghi ở đây theo yêu cầu — file này chỉ liệt kê gap về thiết kế/độ hoàn thiện của tool.

## Bối cảnh

`hr_query` là tool **duy nhất** nối mcp-service với hr-service (rag_search không đụng hr-service). Proxy nhận `(user_id, intent)`, gọi `POST /hr/query` (+ `GET /health` lúc `verify()`), trả thẳng body `{intent, data, summary}`.

### ✅ Đã đúng (không phải gap)
- Boundary an toàn: chỉ nhận `user_id` (client inject từ JWT) + `intent`; không có tham số chọn-người-khác. ✔ ([maintool §Boundary](../maintool/hr_query.md))
- 4 intent MVP `leave_balance / leave_requests / attendance / onboarding` có đủ route + repo + model ở hr-service. ✔ ([src/hr-service/app/api/routes.py](../../../hr-service/app/api/routes.py))
- Auth `X-Internal-Token` truyền qua header ở cả proxy lẫn `verify()`. ✔
- Đăng ký qua registry, mặc định TẮT (`TOOL_HR_QUERY_ENABLED=0`) — không footgun. ✔ ([config.yaml](../../config.yaml))

---

## Gap 2.1 — Proxy không validate/parse `intent` — 🟢 DONE

[hr_query.py:32-43](../../app/tools/hr_query.py#L32-L43) đẩy **thẳng** `intent` string xuống hr-service, không chặn gì.

- Thiết kế ([maintool:111](../maintool/hr_query.md#L111)) yêu cầu: intent ngoài MVP → trả `NotImplementedError` với message rõ ràng, **không lộ data**.
- Hiện tại: intent lạ → hr-service ném **422 thô**, proxy `raise_for_status()` biến thành lỗi tool — không phải thông điệp sạch như hợp đồng.

**Hướng sửa:** proxy giữ allow-list intent MVP của riêng nó; intent ngoài list → trả lỗi/empty có message, không gọi xuống hr-service.

---

## Gap 2.2 — 404 "không có dữ liệu HR" bị coi là lỗi cứng — 🟢 DONE

`raise_for_status()` ([hr_query.py:39](../../app/tools/hr_query.py#L39)) coi mọi non-2xx là exception. Nhưng 404 ("user chưa có bản ghi HR" — [routes.py:63](../../../hr-service/app/api/routes.py#L63)) là **trạng thái hợp lệ**, đáng lẽ trả envelope rỗng kèm `summary` thân thiện.

Bản mock phía query-service đã làm đúng ([mcp_client.py:216-220](../../../query-service/app/infrastructure/external/mcp_client.py#L216-L220)); tool thật thì chưa.

**Hướng sửa:** map 404 → `{intent, data: {}, summary: "Bạn chưa có dữ liệu HR ..."}` ở proxy.

---

## Gap 2.3 — Thiếu audit/trace log + chưa enforce ẩn data nhạy cảm trong `summary` — 🟢 DONE (proxy MVP)

[hr_query.py](../../app/tools/hr_query.py) **không log gì** (cả log thường lẫn audit).

Thiết kế ([maintool:58,115](../maintool/hr_query.md#L58)) yêu cầu intent độ nhạy Cao (`payroll`/`benefits`/`performance`/`recruitment`):
- audit/trace log **mỗi lần** query;
- **không** nhét số/chi tiết nhạy cảm vào `summary` (chỉ xác nhận đã gửi data).

**Hướng sửa:** thêm log mỗi call (intent + user_id hashed, không log payload nhạy cảm); khi mở intent Cao, summary builder phải lược số liệu.

---

## Gap 2.4 — Thiếu role-gate (SA-3) → `payroll` không expose được — 🔴 OPEN (chặn bởi SA)

`payroll` có đủ `PayrollSummaryRecord` + repo `get_payroll` ([postgres_hr_repository.py:129](../../../hr-service/app/infrastructure/db/postgres_hr_repository.py#L129)) nhưng **không nằm trong `Literal`** của `/hr/query` ([routes.py:27](../../../hr-service/app/api/routes.py#L27)).

Nguyên nhân: chưa có cơ chế gate quyền theo JWT claim — **SA-3 còn OPEN** ([maintool:70](../maintool/hr_query.md#L70)). Tool thiếu hẳn tầng phân quyền theo intent.

**Hướng sửa:** chốt SA-3 (claim nào gate intent nhạy cảm) → thêm role-gate ở query-service (inject) + hr-service (enforce) → mới expose payroll.

---

## Gap 2.5 — Độ phủ intent Giai đoạn 2 chưa làm — 🔴 OPEN

Mới có 4 intent MVP. Còn thiếu theo roadmap ([maintool:113](../maintool/hr_query.md#L113)): `payroll` (xem 2.4), `benefits`, `performance`, `recruitment`. `employee_profile`/`org_structure` đã chốt lấy từ JWT claim, **không** thành intent của hr_query (SA-2).

---

## Gap 2.6 — Chịu lỗi mạng / fail-closed coupling ở proxy — 🔴 OPEN

- Chỉ có timeout phẳng 10s ([hr_query.py:29](../../app/tools/hr_query.py#L29)); **không retry, không circuit-breaker** ở tầng mcp→hr (breaker chỉ có phía query-service→mcp).
- `verify()` ([hr_query.py:50-53](../../app/tools/hr_query.py#L50-L53)) gọi `GET /health` lúc startup. Nếu hr-service down, exception **không được catch gọn** ở [main.py:61](../../app/main.py#L61) (chỉ bắt `VectorstoreContractError`) → nếu chạy chung process với rag_search thì kéo cả service không serve được (coupling availability).

**Hướng sửa:** bọc `verify()` hr_query để lỗi health → log cảnh báo + (tùy chọn) disable riêng tool, không chết cả service; cân nhắc retry ngắn ở proxy.

---

## Gap 2.7 — Lệch tập intent query-service ↔ hr-service (contract drift) — 🔴 OPEN (chốt SA)

> Ghi nhận ở mức contract (không phải runtime): query-service phát `{leave_balance, leave_requests, payroll}` còn hr-service chấp nhận `{leave_balance, leave_requests, attendance, onboarding}`. Hai đầu chỉ trùng 2/5; `payroll` và `attendance`/`onboarding` không khớp chiều nào.

**Hướng sửa:** SA chốt 1 tập intent chuẩn cho `hr_query`, đồng bộ Literal hai phía + docs (`contracts.md`).

---

## Gap 2.8 — Doc `maintool/hr_query.md` stale — 🟢 DONE

[maintool/hr_query.md:3,140](../maintool/hr_query.md#L3) vẫn ghi "chưa có gì ở mcp-service / hr_query chưa đăng ký", trong khi tool **đã chạy** qua HTTP proxy + hr-service đã tách riêng. Cần cập nhật trạng thái (MVP done + trỏ sang file gap này cho phần chưa làm).

---

## Mang sang từ Gap 1 (còn OPEN, liên quan hr_query)

### Gap 1.4 — `tool_routing_mode` vẫn mặc định `legacy` — 🔴 OPEN
Native routing là cơ chế để hr_query (và mọi tool mới) **tự lộ động** sang model qua `list_tools()` mà không sửa query-service. Nhưng default vẫn `legacy` vì 2 blocker ([gap1.md:85-89](./gap1.md#L85)):
1. Bug native rớt `outcome` ở nhánh `_fallback` ([orchestration.py](../../../query-service/app/application/use_cases/query/orchestration.py) ~dòng 434/443) → `KeyError: 'outcome'`.
2. ~21 test legacy pin hành vi cũ, cần migrate.

→ Tới khi bật `native`, việc thêm/sửa intent hr_query vẫn phụ thuộc đường legacy ở query-service.

### Gap 1.1 (dư nợ) — `McpSettings` chưa co về cấp-service — 🟡 OPEN (tùy chọn, vệ sinh)
`McpSettings` vẫn giữ field phẳng của rag_search làm carrier ([gap1.md:23,95](./gap1.md#L23)). Không chặn việc thêm tool, nhưng nếu hr_query về sau cần config có cấu trúc thì nên hoàn tất strangler cho `SearchService` nhận thẳng `RagSearchConfig`.

---

## Ưu tiên xử lý

| # | Gap | Cần SA? | Chi phí | Ghi chú |
|---|---|:---:|:---:|---|
| 2.2 | 404 → envelope mềm | Không | Thấp | ✅ DONE (`c52c258`) |
| 2.1 | Validate intent ở proxy | Không | Thấp | ✅ DONE (`c52c258`) |
| 2.3 | Audit log + ẩn summary nhạy cảm | Không | Thấp-TB | ✅ DONE cho proxy MVP |
| 2.8 | Cập nhật doc stale | Không | Thấp | ✅ DONE (`c52c258`) |
| 2.6 | Tách verify khỏi fail-closed | Không | TB | |
| 2.7 | Chốt tập intent | **Có** | — | Quyết định contract |
| 2.4 | Role-gate payroll (SA-3) | **Có** | TB | Chờ SA-3 |
| 2.5 | Intent Giai đoạn 2 | **Có** | Cao | Sau 2.4 |

**DoD nhóm rẻ (2.1/2.2/2.3/2.8):** intent lạ → message sạch (không 422 thô); 404 → envelope rỗng có summary; mỗi call có log; doc khớp thực tế. `pytest src/mcp-service/tests -q` xanh.

---

# Hướng dẫn thực thi cho dev — ĐỌC KỸ trước khi sửa

> Mục tiêu: sửa được nhóm gap rẻ (2.1/2.2/2.3/2.8) mà **không làm bể** mcp-service. Phần lớn chỉ đụng **1 file** `app/tools/hr_query.py` + test của nó. Nếu thấy mình phải sửa `build_mcp`, `main.py`, `McpSettings`, hay `config.yaml` → **dừng lại**, bạn đang đi quá phạm vi (trừ 2.6/2.8).

## 9.1 ĐỌC TRƯỚC (bắt buộc, theo thứ tự)

1. [docs/refactor/tool-registry.md §2 "BẤT BIẾN KHÔNG ĐƯỢC PHÁ"](../refactor/tool-registry.md#2-bất-biến-không-được-phá-flow-run-invariants) — luật chung của tool layer.
2. [app/tools/base.py](../../app/tools/base.py) — port `McpTool` (`register`/`verify`/`aclose`) + cách `register_tool` hoạt động.
3. [app/tools/hr_query.py](../../app/tools/hr_query.py) — file bạn sẽ sửa. Hiểu vòng đời client (lazy `_get_client` → `verify()` → `aclose()`).
4. [app/tools/rag_search.py](../../app/tools/rag_search.py) — **tool mẫu**: cách dùng `logging.getLogger("mcp-service")`, cách `verify()` log rồi tự dọn, cách register `@mcp.tool()` giữ typed signature. Bám sát style này.
5. [tests/test_hr_query_tool.py](../../tests/test_hr_query_tool.py) — bộ test hiện có. Bạn **thêm** test, **không** sửa test cũ (trừ khi gap yêu cầu đổi hành vi đã được chốt).
6. [docs/maintool/hr_query.md](../maintool/hr_query.md) — hợp đồng (envelope `{intent,data,summary}`, boundary, intent độ nhạy).
7. [src/hr-service/app/api/routes.py](../../../hr-service/app/api/routes.py) — đầu kia của proxy: mã lỗi (404/422), shape response thật.

## 9.2 BẤT BIẾN KHÔNG ĐƯỢC PHÁ (chiếu riêng cho hr_query)

| # | Bất biến | Vì sao |
|---|---|---|
| I1 | **Signature tool giữ nguyên `hr_query(user_id: str, intent: str) -> dict`.** Không thêm param định danh (vd `target_user_id`). | Boundary an toàn — không có đường hỏi data người khác ([maintool §Boundary](../maintool/hr_query.md)). `user_id` do client inject từ JWT. |
| I2 | **Envelope trả về luôn có key `summary` (str).** Kể cả nhánh 404/empty/lỗi-mềm. | query-service `_handle_hr` chỉ đọc `.summary`/`.intent` (invariant #5 tool-registry). Thiếu `summary` → vỡ chat. |
| I3 | **`verify()` xong phải `aclose()` client tạo lúc verify.** Giữ pattern lazy `_get_client` + đóng trong `aclose`. | "Drop-client-sau-verify": client phải bind đúng event loop của uvicorn lúc serve (invariant #2). `main._verify_and_reset` gọi `aclose` trong `finally`. |
| I4 | **`verify()` không được nuốt lỗi contract của tool khác.** Đừng đổi `main.py` để catch chung chung. | Startup fail-closed của `rag_search` phải còn (invariant #1). Xem 2.6 nếu thật sự cần nới — làm PR riêng. |
| I5 | **Auth header `X-Internal-Token` giữ nguyên** ở cả POST và GET. | Test `test_verify_hits_health_endpoint` + bảo mật internal. |
| I6 | **200 OK passthrough nguyên body** `{intent,data,summary}` từ hr-service. Không reshape response thành công. | Test `test_proxy_*_shape` assert `result == payload`. Việc parse `data` là của query-service, không phải proxy. |
| I7 | **5xx vẫn `raise`.** Chỉ 404 mới được "mềm hóa" (2.2). | Test `test_proxy_raises_on_http_error` (503) phải còn xanh. 5xx = lỗi hạ tầng thật, không được nuốt. |

## 9.3 Quy ước codebase phải tuân

- **SRP / 1 tool = 1 file:** mọi logic hr_query nằm trong `app/tools/hr_query.py`. Hằng số (allow-list intent) đặt ngay đầu file, không tạo module config mới.
- **Config qua `params`, KHÔNG thêm field vào `McpSettings`:** hr_query đọc `params["params"]["hr_service_url"]/["internal_token"]`. Nếu cần config mới (vd timeout, retry) → thêm key vào `hr_query.params` trong [config.yaml](../../config.yaml) + đọc qua `params`, **đừng** đụng dataclass `McpSettings` (tránh phình god-object — xem [gap1 dư nợ 1.1](./gap1.md#L29)).
- **Logger:** `logging.getLogger("mcp-service")` (cùng namespace rag_search), format do `main.py` set. Đừng `print`.
- **Không thêm dependency nặng:** mcp-service requirements tối thiểu; hr_query chỉ cần `httpx` (đã có). Không kéo `boto3`/SQLAlchemy/...
- **Không đụng đường dữ liệu:** proxy không fetch file, không query DB — chỉ gọi HTTP hr-service.
- **Tiếng Việt cho `summary`** (khớp hr-service); message lỗi/log có thể tiếng Anh.

## 9.4 Recipe từng gap (nhóm rẻ)

### 2.1 — Allow-list intent ở proxy
- Thêm hằng `MVP_INTENTS = {"leave_balance", "leave_requests", "attendance", "onboarding"}` đầu file (đúng tập hr-service `Literal` hiện tại — [routes.py:27](../../../hr-service/app/api/routes.py#L27)).
- Trong `_call` (hoặc trong hàm `hr_query` đăng ký), nếu `intent not in MVP_INTENTS` → **không gọi xuống hr-service**, trả envelope mềm: `{"intent": intent, "data": {}, "summary": "Intent '<intent>' chưa được hỗ trợ."}` (giữ I2). Không lộ data.
- ⚠️ `payroll` hiện query-service vẫn phát (gap 2.7) → sẽ rơi vào nhánh này và nhận message sạch thay vì 422. Đó là hành vi mong muốn cho tới khi SA chốt 2.7/2.4.
- **Test thêm:** `test_proxy_rejects_unknown_intent` — gọi `fn(USER_HR, "payroll")`, assert không có call POST nào (`client.calls == []`) và `result["summary"]` chứa thông báo.

### 2.2 — 404 → envelope mềm
- Bắt riêng 404 **trước** `raise_for_status()`: nếu `response.status_code == 404` → return `{"intent": intent, "data": {}, "summary": "Bạn chưa có dữ liệu HR cho mục này."}`.
- Mọi status khác giữ nguyên `raise_for_status()` (I7 — 5xx vẫn raise).
- **Test thêm:** `test_proxy_soft_404` — `post_response=FakeResponse(404, {"detail": "no HR data"})`, assert `result["data"] == {}` và `result["summary"]` không rỗng, **không** raise.
- **Không sửa** `test_proxy_raises_on_http_error` (503) — nó phải vẫn pass.

### 2.3 — Logging (+ chuẩn bị ẩn data nhạy cảm)
- Thêm `logger = logging.getLogger("mcp-service")` đầu file (như rag_search).
- Log 1 dòng mỗi call **trước/sau** khi gọi: `logger.info("hr_query intent=%s user=%s status=%s", intent, _mask(user_id), status)`. **Không** log `body`/`data` (tránh rò dữ liệu cá nhân).
- `_mask(user_id)`: chỉ log 8 ký tự đầu hoặc hash ngắn — không log full PII.
- Ghi chú sẵn cho Giai đoạn 2: khi mở intent độ nhạy Cao, summary builder (phía hr-service) phải lược số liệu — không phải việc của proxy, nhưng proxy phải có **audit log** cho các intent đó ([maintool:58,115](../maintool/hr_query.md#L58)).
- **Test (tùy chọn):** dùng `caplog` assert có record `hr_query intent=...`.

### 2.8 — Cập nhật doc stale
- Sửa [maintool/hr_query.md](../maintool/hr_query.md) dòng 3 và 140: đổi trạng thái từ "chưa có gì ở mcp-service / chưa đăng ký" → "✅ đã chạy qua HTTP proxy sang hr-service (4 intent MVP); phần chưa làm xem `docs/gap/gap2.md`".
- Chỉ sửa câu trạng thái, giữ phần thiết kế (domain/boundary/SA blockers) làm tham chiếu.

> **2.6 (verify non-fatal) và 2.4/2.5/2.7 KHÔNG nằm trong nhóm rẻ.** 2.6 đụng `main.py` (chia sẻ với rag_search) → PR riêng, phải chứng minh `rag_search` vẫn fail-closed (I4). 2.4/2.5/2.7 chờ SA-3 + chốt contract intent.

## 9.5 Chạy test & không làm vỡ gì

```bash
# Toàn bộ test mcp-service (phải xanh sau khi sửa)
pytest src/mcp-service/tests -q
# Riêng tool hr_query khi đang code
pytest src/mcp-service/tests/test_hr_query_tool.py -q
```

Các test **phải còn xanh** (đừng sửa để "cho qua"):
- `test_hr_query_tool.py`: `test_proxy_*_shape` (I6), `test_proxy_raises_on_http_error` (I7), `test_verify_hits_health_endpoint` (I5), `test_aclose_closes_client` (I3).
- `test_tool_registry.py` / `test_mcp_server.py`: đăng ký + build_mcp (đừng đổi cách `register_tool`).
- `test_config.py`: `tool_spec()` (đừng đổi cấu trúc `params`).

Sau khi sửa ở mcp-service, **không cần** đụng query-service cho nhóm rẻ — `_handle_hr` chỉ đọc `.summary`/`.intent`, mà ta luôn giữ `summary` (I2). Nếu vẫn lo, chạy thêm `pytest src/query-service/tests/test_acl.py -q` (test ACL inject user_id cho hr_query).

## 9.6 Checklist trước khi mở PR

- [ ] Chỉ đụng `app/tools/hr_query.py` + `tests/test_hr_query_tool.py` (+ `docs/maintool/hr_query.md` cho 2.8). Không đụng `build_mcp`/`main.py`/`McpSettings`/`config.yaml`.
- [ ] Signature `hr_query(user_id, intent)` không đổi (I1); envelope luôn có `summary` (I2).
- [ ] 200 passthrough nguyên vẹn (I6); 5xx vẫn raise (I7); chỉ 404 + intent-lạ được mềm hóa.
- [ ] `verify()` vẫn `aclose()` client (I3); không đổi catch ở `main.py` (I4).
- [ ] Không log payload/PII đầy đủ; có log mỗi call.
- [ ] `pytest src/mcp-service/tests -q` xanh; có test mới cho 404 + intent-lạ.
- [ ] Không thêm dependency mới vào `requirements.txt`.
