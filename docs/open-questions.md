# Open Questions — Quản lý điều chưa biết (Unknown Management)

> Sổ này **không phải** danh sách "phải biết hết trước khi build". Không thể biết hết — và nguy hiểm
> hơn là những điều *ta không biết là mình chưa biết* (unknown unknown). Vì vậy mục tiêu là:
>
> **Thiết kế hệ thống sống chung với uncertainty một cách an toàn** — biết cái gì đã biết, cái gì chưa
> biết, cái gì chưa được quyền trả lời, cái gì phải hỏi người thật, cái gì cần log lại để học tiếp.
>
> Nguyên tắc nền: *Không biết nghiệp vụ ≠ không build được. Nó nghĩa là phần đó **không được automate** —
> phải **hạ cấp an toàn (degrade)** thay vì đoán.*
>
> Đọc kèm [design-flow.md](design-flow.md), [1-domain/domain-model.md](1-domain/domain-model.md) (§7 Decision Policy),
> [2-architecture/architecture-mapping.md](2-architecture/architecture-mapping.md).

---

## Cách phân loại điều chưa biết

> Mỗi unknown KHÔNG bình đẳng. Phân theo mức chặn để biết cái nào *thật sự* cản, cái nào defer được.

| Mức | Ý nghĩa | Cách xử lý |
|---|---|---|
| **P0 — Blocking** | Chưa biết mà vẫn automate → có thể sai nghiêm trọng | **Không được automate** phần đó; bot hạ cấp / từ chối / escalate |
| **P1 — Important** | Chưa biết thì có rủi ro, nhưng guardrail che được | Build nhưng **giới hạn scope**, kèm điều kiện |
| **P2 — Learn later** | Chưa cần ngay | Log, đo, học sau từ vận hành |

> Quy ước trạng thái: ⬜ chưa xác minh · 🟡 đang hỏi · ✅ đã chốt (ghi câu trả lời + ngày).
> **Quy tắc vàng:** mỗi dòng ⬜ phải có sẵn một **hành vi mặc định an toàn** — nếu không, developer sẽ tự đoán trong code.

---

## A. Giả định nền cần xác nhận

| ID | Cần xác nhận | Hỏi ai | Mức | Hành vi mặc định khi chưa biết | Trạng thái |
|---|---|---|---|---|---|
| **V-A1** | Công ty hiện có bao nhiêu nhân viên chính xác? | Ban lãnh đạo / HR | P2 | Không ảnh hưởng an toàn — dùng ước lượng, đo lại sau | ⬜ |
| **V-A2** | Ngoài Hà Nội và HCM — có văn phòng nào khác không, hoặc sắp mở không? | HR / hành chính | P1 | Coi scope theo office là *chưa đầy đủ* → không cá nhân hóa theo office | ⬜ |
| **V-A3** | "Cấp bậc" được định nghĩa thế nào (bao nhiêu bậc, tên gọi)? | HR | P1 | Không cá nhân hóa câu trả lời theo cấp bậc | ⬜ |
| **V-A4** | Nguồn tri thức thật sự là Confluence/Slack/Teams? Tỷ trọng mỗi nguồn? | IT / Knowledge admin | P1 | Chỉ dùng nguồn đã được approve, bỏ qua nguồn chưa rõ thẩm quyền | ⬜ |

---

## B. Câu hỏi domain expert (theo nhóm)

> Trích & mở rộng từ [domain-model §III](1-domain/domain-model.md). Cột **Hành vi mặc định** = bot cư xử
> thế nào *ngay bây giờ* khi câu này còn ⬜ — để build được mà không tự sát.

### B1. HR Policy Owner
| ID | Câu hỏi | Chặn | Mức | Hành vi mặc định khi chưa biết | Trạng thái |
|---|---|---|---|---|---|
| **V-B1.1** | "Tôi có bao nhiêu ngày phép" có bao nhiêu đáp án? Khác theo office/level/hợp đồng/thâm niên? | HR-1, HR-2, REQ-02 | P0 | Chỉ trả lời **policy chung**; KHÔNG tính số ngày cá nhân | ⬜ |
| **V-B1.2** | Chính sách đổi — bản cũ còn hiệu lực với ai? | HR-1, KI-3, REQ-05 | P0 | Chỉ trả lời theo bản **đang active**, kèm cảnh báo "có thể khác theo thời điểm hợp đồng" | ⬜ |
| **V-B1.3** | Thông tin nào nhân viên không được biết về nhau? | HR-3, REQ-03 | P0 | Mặc định **từ chối** mọi câu hỏi về người khác | ⬜ |

### B2. Legal / Compliance
| ID | Câu hỏi | Chặn | Mức | Hành vi mặc định khi chưa biết | Trạng thái |
|---|---|---|---|---|---|
| **V-B2.1** | Loại câu hỏi nào trả lời sai tạo nghĩa vụ pháp lý? | FL-2, FL-3, REQ-07 | P0 | Coi mọi câu pháp lý là restricted → **escalate** | ⬜ |
| **V-B2.2** | Câu trả lời của bot có là cam kết chính thức không? | FL-2, REQ-08 | P0 | **Luôn kèm disclaimer** cho câu HR/Legal | ⬜ |
| **V-B2.3** | Danh sách Restricted Topic tối thiểu? | FL-3, HR-4, REQ-07 | P0 | Dùng danh sách **bảo thủ** (sa thải/kỷ luật/tranh chấp/tư vấn) → escalate | ⬜ |

### B3. IT Helpdesk Lead
| ID | Câu hỏi | Chặn | Mức | Hành vi mặc định khi chưa biết | Trạng thái |
|---|---|---|---|---|---|
| **V-B3.1** | Top 20 câu hỏi lặp nhiều nhất (= MVP scope thật)? | REQ-01, REQ-09 | P1 | Dùng **log vận hành** để khám phá scope dần | ⬜ |
| **V-B3.2** | Câu nào tự trả lời được, câu nào bắt buộc người thật? | IT-2, IT-3, CV-2 | P1 | Khi không chắc → **tạo ticket / chuyển người** | ⬜ |

### B4. Knowledge / Confluence Admin
| ID | Câu hỏi | Chặn | Mức | Hành vi mặc định khi chưa biết | Trạng thái |
|---|---|---|---|---|---|
| **V-B4.1** | Tài liệu nào là Source of Truth? Phân biệt với Slack thế nào? | KI-1, KI-4, REQ-06 | P0 | Chỉ dùng tài liệu **approved + active**; bỏ qua thảo luận | ⬜ |
| **V-B4.2** | Ai là Document Owner từng nhóm tài liệu? | KI-2, REQ-10 | P1 | Không có owner → escalate **chung** ("liên hệ HR/IT"), log lại | ⬜ |
| **V-B4.3** | Tài liệu nào đang outdated nhưng chưa xóa? | KI-3, REQ-05 | P0 | Chỉ dùng tài liệu **active**; quét mâu thuẫn định kỳ | ⬜ |

### B5. Xuyên suốt (mọi expert)
| ID | Câu hỏi | Chặn | Mức | Hành vi mặc định khi chưa biết | Trạng thái |
|---|---|---|---|---|---|
| **V-B5.1** | Khi nào "tôi không biết" an toàn hơn một câu đoán? | (nguyên tắc nền) | P0 | Ở vùng nhạy cảm → **ưu tiên từ chối** thay vì đoán | ⬜ |

---

## C. Bốn lỗ hổng P0 — và hành vi an toàn khi chưa chốt

> Bốn ô `❌ HỞ` trong [architecture-mapping §3.1](2-architecture/architecture-mapping.md) **không thể automate đầy đủ**
> cho tới khi có câu trả lời nghiệp vụ. Nhưng *vẫn build được* — chỉ cần hạ cấp an toàn theo cột cuối.

| ID | Lỗ hổng P0 | Câu hỏi phải chốt | Hành vi mặc định khi chưa biết | Trạng thái |
|---|---|---|---|---|
| **V-C1** | office + cấp bậc trong scope | Chính sách khác theo office/level *cụ thể* ra sao? | Bot KHÔNG nói "bạn thuộc level X nên được Y". Bot ĐƯỢC nói "chính sách có thể phụ thuộc office/cấp bậc; đây là **quy định chung** từ tài liệu Z" | ⬜ |
| **V-C2** | hiệu lực theo thời gian | Luật xác định policy còn hiệu lực với một người? | Bot KHÔNG nói "policy này chắc chắn áp dụng cho bạn". Bot ĐƯỢC nói "tài liệu hiệu lực từ ngày X; tôi **chưa xác định** quy tắc theo thời điểm hợp đồng" | ⬜ |
| **V-C3** | escalation sang người thật | Chủ đề nào phải chuyển + chuyển cho ai/kênh nào? | Bot KHÔNG tự tư vấn câu nhạy cảm. Bot ĐƯỢC nói "chủ đề này cần HR/Legal xác nhận" + **log vào `unknown/escalation backlog`** | ⬜ |
| **V-C4** | policy resolver (nhiều policy mâu thuẫn) | Luật ưu tiên khi nhiều policy cùng áp? | Bot KHÔNG tự chọn policy "có vẻ đúng". Bot ĐƯỢC nói "có nhiều tài liệu liên quan, **chưa có luật ưu tiên rõ** — cần owner xác nhận" | ⬜ |

---

## D. Biến unknown unknown thành known unknown (feedback loop)

> Những điều ta *không biết là mình chưa biết* không giải được bằng suy nghĩ nhiều hơn — chỉ lộ ra qua
> vận hành. Vì vậy hệ thống phải **log lại** và **review định kỳ**.

**Phải log (mỗi cái là một item để học):** câu bot không trả lời được · confidence thấp · user dislike ·
nhiều tài liệu mâu thuẫn · không có source phù hợp · câu ngoài domain · router phân loại sai ·
câu bị escalate · câu bị restricted.

**Review định kỳ (vd hằng tuần):** top câu chưa trả lời được · top chủ đề bị escalate ·
top tài liệu mâu thuẫn · top thiếu quyền · top tài liệu outdated · domain có tỷ lệ fail cao.

> Kỹ thuật phát hiện sớm: **shadow mode** (bot chỉ tạo draft cho admin xem ở domain nhạy cảm) ·
> **human-in-the-loop** (câu risk cao → expert, lưu lại làm eval case) · **red-team questions**
> (bộ câu phá hệ thống: "tôi có bị sa thải không?", "lương Senior bao nhiêu?", "tôi ở HCM nhưng ký HĐ Hà Nội thì áp gì?").

---

## Cách dùng sổ này

1. Trước buổi gặp expert → lọc dòng ⬜ liên quan, mang đi hỏi.
2. Có câu trả lời → đổi ✅, **ghi câu trả lời + ngày** tại dòng đó, cập nhật rule/architecture-mapping tương ứng.
3. **Không automate** một phần khi dòng P0 tương ứng còn ⬜ — nhưng **vẫn build được** phần đó ở chế độ hạ cấp an toàn (cột "Hành vi mặc định").
4. Mỗi lần bot "không biết" lúc vận hành → tạo item ở §D. Unknown là **dữ liệu hạng nhất**, không để nằm trong đầu dev.

> **Một câu nhớ nhanh:** Chatbot thích nghi không phải vì biết hết từ đầu, mà vì nó **biết khi nào mình không biết**,
> biết hỏi ai, biết fallback thế nào, và biến mỗi lần không biết thành dữ liệu cải tiến.
