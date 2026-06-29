# Kế hoạch THỰC THI Observability — để đội dev vào hoàn thiện toàn bộ

> Tài liệu thi công, đi kèm `observability-plan.md` (kiến trúc & lý do). Đây là phần "team vào làm":
> readiness artifacts, bóc epic/ticket theo phase, Definition of Done, ownership, trình tự kickoff.
> Trạng thái: đề xuất. Mỗi ticket nghiệm thu bằng Task Contract tương ứng (§3 của plan).

---

## 0. Nguyên tắc thi công
- **Schema trước, code sau.** Không instrument khi field chưa chốt.
- **Golden path trước, fan-out sau.** 1 service mẫu xong mới nhân rộng.
- **Task Contract = Definition of Done.** Ticket xong khi span/metric phát đúng field hợp đồng.
- **App không bao giờ phụ thuộc observability.** Mọi thứ best-effort, rollback được.
- **Mỗi phase tự có giá trị.** Không chờ phase cuối mới thấy lợi ích.

---

## 1. Readiness artifacts — PHẢI có trước khi fan-out

| # | Artifact | Mục đích | Chặn ai | Trạng thái |
|---|---|---|---|---|
| A | **Canonical Schema** (`observability-semantic-conventions.md`) | Mọi field chuẩn + kiểu + bắt buộc/tùy chọn | TẤT CẢ instrument | ⬜ chưa làm (blocker #1) |
| B | **Golden path** — 1 service instrument đầy đủ làm mẫu | Bản copy cho service khác | Fan-out | ⬜ |
| C | **Hướng dẫn instrument** (cách thêm span, đặt tên, truyền traceparent, test) | Dev tự làm không hỏi | Fan-out | ⬜ |
| D | **Local stack** (Collector+Tempo+Loki trong docker-compose) | Dev chạy local thấy trace ngay | Hiệu suất dev | ⬜ |
| E | **Ticket breakdown + ownership** (tài liệu này §3 + team-ownership.md) | Không task mồ côi, không chờ nhau | Điều phối | ⬜ |
| F | **Quyết định cần duyệt** (§5) | Tránh làm xong rồi đổi | Khởi động | ⬜ |

---

## 2. Lộ trình phase (tham chiếu plan §6) — góc nhìn thực thi

| Phase | Mục tiêu | Lấp câu hỏi | Phụ thuộc |
|---|---|---|---|
| 0 | Canonical schema + điền nốt Task Contract | nền | — |
| 1 | OTel Collector + Alertmanager (alert AI Router) | 1, 7 | Phase 0 (field) |
| 2 | OTel hóa toàn bộ service, bọc span mọi task | 2, 4 | Phase 0,1, golden path |
| 3 | Tempo+Loki + exporters hạ tầng + GCP billing | 2,4,5 | Phase 2 |
| 4 | Dashboard 7 câu + RED per-service + dọn NR/LangSmith | 1,2,3,5,7 | Phase 3 |
| 5 | Quality + Config/Policy Store + 2 công tắc | 6 + control plane | Phase 2,4 |

---

## 3. Bóc EPIC → TICKET theo phase (DoD = Task Contract)

### EPIC 0 — Nền (Phase 0)
| Ticket | DoD | Owner đề xuất |
|---|---|---|
| 0.1 Soạn Canonical Schema | Mọi field §3 plan có tên/kiểu/bắt buộc; cả team review | devops + lead |
| 0.2 Điền nốt Task Contract ~19 task còn lại | Mỗi task có input/output/success/SLO(placeholder)/cost/deps/retry/observability | mỗi service owner |
| 0.3 Storage policy | **Sample 100% (trace toàn bộ).** Tempo/Loki cap **≤4GB RAM (ingester)** → tự spill xuống disk, đọc lại trong retention. Retention: trace 7d, log 14d, metric 15d (điều chỉnh sau theo dung lượng) | devops |
| 0.4 Định nghĩa **PII redaction policy** | Trace toàn bộ NHƯNG scrub field nhạy cảm (lương/CCCD/HR) tại Collector trước khi lưu | devops + security |

### EPIC 1 — Collector + Alerting (Phase 1)
| Ticket | DoD | Owner |
|---|---|---|
| 1.1 Dựng OTel Collector (idle) trong compose | Collector chạy, processor chuẩn hóa theo schema 0.1, **redaction 0.4** | devops |
| 1.2 Local stack (artifact D) | `docker compose up` local thấy được pipeline | devops |
| 1.3 Alertmanager + rule AI Router | Ép key cạn quota → nhận alert Slack; rule: fallback spike, quota burndown, key_cooldown, no_capacity | devops |
| 1.4 Runbook cho mỗi alert | Mỗi alert có link runbook hành động | devops + service owner |

### EPIC 2 — OTel hóa toàn hệ (Phase 2)
> Golden path (artifact B) = service đầu tiên trong đợt 2a, làm xong mới fan-out.

| Ticket | DoD | Owner |
|---|---|---|
| 2a.1 **Golden path**: instrument 1 service xương sống đầy đủ + hướng dẫn (C) | Trace+metric đúng schema; tài liệu copy-được | lead |
| 2a.2 nginx sinh `trace_id` gốc + truyền traceparent | 1 request có trace_id xuyên nginx→query→airouter | gateway owner |
| 2a.3 Bọc span task hiện mù: `vector_search`, `embed_query`, `rerank`, `output.validate` | Span phát latency/hits/top_score/status theo §3.4 | mcp + query owner |
| 2a.4 **mcp-service thêm tracer** (hiện chưa có) | rag_search có span con cho từng bước | mcp owner |
| 2b.1 Instrument user/document/hr-service | RED + span nghiệp vụ theo contract | mỗi owner |
| 2b.2 rag-worker: ghi token+cost embed/caption | generation có usage/cost (fix lỗ hổng cost) | rag-worker owner |
| 2c.1 Frontend chat+admin: trace + error, nhận trace_id | click user lần được xuống LLM | FE owner |

### EPIC 3 — Backend lưu trữ + cost hạ tầng (Phase 3)
| Ticket | DoD | Owner |
|---|---|---|
| 3.1 Tempo + Loki vào compose (cap ≤4GB RAM, spill disk), cắm Grafana datasource | Click biểu đồ→trace→log cùng trace_id; RAM observability ≤4GB | devops |
| 3.2 node-exporter + cAdvisor | CPU/RAM/đĩa per service lên Grafana | devops |
| 3.3 postgres/redis/qdrant exporter | latency + tài nguyên hạ tầng | devops |
| 3.4 Kéo GCP billing/Monitoring (GCS egress, VM) | cost storage+compute lên dashboard | devops |
| 3.5 SLO/threshold: **default + tunable + history** | Ship số mặc định mỗi task (alert chạy ngay); devops chỉnh tay runtime qua Config Store (`/admin/ops/*`); mọi lần đổi ghi audit (ai/từ→tới/lúc nào/vì sao). Dữ liệu baseline = gợi ý tinh chỉnh, không phải điều kiện chặn. | devops + owners |

### EPIC 4 — Dashboard + dọn dẹp (Phase 4)
| Ticket | DoD | Owner |
|---|---|---|
| 4.1 Dashboard 7 câu hỏi (plan §5) | Một URL trả lời 7 câu | devops |
| 4.2 RED per-service + impact theo role/department | câu 3 (ai/bao nhiêu) có số | devops |
| 4.3 Nhúng `/admin/ops/*` gate devops | Team xem qua admin FE | FE + devops |
| 4.4 Gỡ New Relic + LangSmith | giữ Langfuse; bỏ 2 cloud trùng | devops |

### EPIC 5 — Quality + Control Plane nền (Phase 5)
| Ticket | DoD | Owner |
|---|---|---|
| 5.1 Feedback (👎) gắn trace lên dashboard | xem được feedback âm theo trace_id | query + devops |
| 5.2 2 điểm chất lượng: `retrieval.relevance`, `groundedness` | trace có 2 score; kịch bản §5b chẩn được | query owner |
| 5.3 **Config/Policy Store** trung tâm | 1 nơi giữ config động (model/threshold/strategy) | devops + lead |
| 5.4 Mọi service đọc model/threshold **runtime** (nền Công tắc B) | đổi model KHÔNG restart | mỗi owner |
| 5.5 Công tắc A (sampling runtime) + Human gate 3 nấc | bật/tắt trace toàn hệ; apply qua gate + audit | devops |

---

## 4. Trình tự kickoff

```
Tuần 0:  EPIC 0 (schema + retention + PII)  ── blocker, cả team duyệt, KHÔNG fan-out
Tuần 1:  EPIC 1 (Collector+Alert+local) ──┬── golden path 2a.1 + hướng dẫn
                                          └── bóc ticket + map owner xong
Tuần 2+: EPIC 2 fan-out (mỗi owner 1 service, copy golden path)
Tuần N:  EPIC 3 → 4 → 5 tuần tự
```
**Quy tắc vàng:** Tuần 0–1 chỉ 1-2 người. Cả đội nhảy vào *sau khi* có schema + golden path + hướng dẫn. Fan-out sớm = 8 kiểu instrument lệch nhau.

---

## 5. Quyết định cần duyệt trước khi khởi động (artifact F)
1. **Self-host stack (Grafana+Tempo+Loki+Collector)** — đã chốt (thay NR/LangSmith). ✅
2. **VM 16GB giữ chung hay tách VM observability?** — giữ chung; Tempo/Loki cap ≤4GB RAM + spill disk → còn 12GB cho app. ✅ (chốt theo quyết định storage)
3. **OTel SDK ngôn ngữ** — Python (auto-instrument FastAPI/httpx) + JS (frontend Nuxt). → chuẩn OpenTelemetry.
4. **PII** — chốt: **trace toàn bộ** nhưng scrub field nhạy cảm (lương/CCCD/HR) tại Collector. Cần security xác nhận danh sách field scrub.
6. **Access control (MVP — giữ đơn giản, chốt):**
   - **Tầng Xem:** login thường (dev/staff) → dashboard read-only.
   - **Tầng Tune:** **1 top-secret account duy nhất, đúng 1 người**, token **dài hạn**, account **tách biệt bên ngoài**, dev thường KHÔNG được chạm.
   - Hoãn sau MVP: dual-control, secret per-người, token ngắn hạn, xoay vòng.
   - **Ưu tiên: dashboard workable (Phase 0→4) TRƯỚC**; Công tắc B + control plane (Phase 5) làm sau, chỉ cần để nền Config Store sẵn.
5. **Ai là owner tổng (DRI) của observability** — 1 người chịu trách nhiệm cuối. → cần chỉ định.

---

## 6. Definition of Done toàn cục (khi nào coi là "xong")
- [ ] 1 `trace_id` xuyên suốt frontend→nginx→backend→ai-router→LLM
- [ ] 25 task §1.2 đều 🟢 trace + cost + latency
- [ ] Dashboard 1 cửa trả lời 7 câu hỏi, nhúng `/admin/ops/*`
- [ ] Alert theo SLO (đo từ baseline) + runbook gắn kèm
- [ ] Kịch bản §5b chẩn được "user than trả lời sai"
- [ ] PII được scrub; retention per signal áp dụng
- [ ] New Relic + LangSmith đã gỡ
- [ ] Config/Policy Store + 2 công tắc + human gate sẵn (nền control plane)
- [ ] AIOps: agent ráp được qua cổng apply mà không sửa kiến trúc
