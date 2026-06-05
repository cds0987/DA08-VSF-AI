# GUIDELINE — Tinh thần khi thay đổi hệ thống

> Đây là **soft guide** — định hướng, không phải luật chi tiết. Nó nói về *cách tư duy* khi thêm,
> sửa, hoặc xóa bất cứ thứ gì, chứ không quy định công nghệ hay cách code cụ thể (đó là việc của tầng
> kỹ thuật, sẽ thay đổi theo thời gian).
>
> Bối cảnh: đọc kèm [docs/design-flow.md](docs/design-flow.md) để hiểu chuỗi thiết kế 5 tầng.

---

## Tinh thần cốt lõi

> **Đi từ trên xuống. Không đổi gì trong im lặng. Đừng chạm vào cái bất khả xâm phạm.**

Mỗi thay đổi nên trả lời được một câu: *"Tôi phục vụ nhu cầu nghiệp vụ nào?"* — nếu không trả lời được,
hãy dừng lại và hỏi trước khi code.

---

## Năm định hướng mềm

### 1. Bắt đầu từ "tại sao", không từ "code"
Trước khi viết kỹ thuật, hãy chắc thay đổi này gắn với một *nhu cầu* và một *quy tắc nghiệp vụ*. Code là
bước cuối, không phải bước đầu. Nếu một tầng phía trên còn trống (chưa có lý do rõ) → bổ sung nó trước.

### 2. Làm từng lát mỏng, được phép quay lại
Không cần hoàn hảo cả hệ thống mới làm. Đi một lát cắt nhỏ xuyên suốt từ nhu cầu đến hiện thực, học được
gì thì quay lên chỉnh phần trên. Tiến hóa dần tốt hơn thiết kế cứng một lần.

### 3. Không thay đổi câm
Thứ bạn đổi nên để lại dấu vết và người liên quan nên biết. "Tiện tay sửa thêm" mà không nói ra là nguồn
gốc của lệch pha. Khi nghi ngờ — báo, hỏi, ghi lại.

### 4. Bảo vệ cái cốt lõi
Có một số nguyên tắc nghiệp vụ là *lý do tồn tại* của hệ thống (xem các quy tắc 🔴 trong
[domain-model](docs/1-domain/domain-model.md)). Đừng làm chúng yếu đi vì tiện hay vì nhanh. Mọi thứ khác
có thể thương lượng; những cái này thì không.

### 5. Tài liệu đi cùng thay đổi
Một thay đổi chưa phản ánh vào tài liệu là một thay đổi *chưa xong*. Không cần viết dài — chỉ cần đủ để
người sau hiểu *vì sao*, không phải đoán.

---

## Hai câu hỏi tự kiểm trước khi merge

1. Thay đổi này có truy ngược được về một lý do nghiệp vụ không?
2. Người bị ảnh hưởng và tài liệu liên quan đã được cập nhật chưa?

Nếu cả hai đều "rồi" → tiếp tục. Nếu một câu còn "chưa" → đó là việc cần làm nốt, không phải việc để sau.

---

> Phần *làm thế nào* cụ thể (công nghệ, cấu trúc thư mục, quy ước code) thuộc về tầng kỹ thuật và sẽ đổi
> theo thời gian. Bản guide này cố tình không nhắc tới chúng — để nó không lỗi thời cùng với code.
