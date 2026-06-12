# GCP Dev — Guardrail chi phí (~$30/tháng)

Tái dựng project dev sau khi `vsf-rag-chatbot-dev` bị xóa, có chốt chặn để **không
sập giữa chừng** và **không cháy túi**.

## Vì sao project cũ chết

`vsf-rag-chatbot-dev` gắn **billing account TRIAL** (`012A5D-72D535-E64681`). Hết
credit trial → account đóng (`OPEN=False`) → GCP suspend mọi resource → project bị
xóa (`DELETE_REQUESTED`). → Project mới **bắt buộc** gắn account trả tiền đang OPEN
(`01BDC1-965FBC-F241D6`).

## 🔒 Nguyên tắc 1-VM

TUYỆT ĐỐI không host service nào ngoài VM. **1 VM duy nhất** chạy toàn bộ stack
in-compose: 6 backend + 2 frontend + nginx + nats + redis + qdrant + langfuse +
langfuse-db + **app-postgres**. KHÔNG Cloud SQL. Ngoại lệ duy nhất: **GCS bucket**
(object storage cho file tài liệu — managed, không phải compute).

## Inventory: cũ vs mới

| | Project cũ (đã xóa) | Project mới (1-VM) |
|---|---|---|
| VM app | `vsf-rag-demo-vm` (8GB) | `vsf-rag-demo-vm` (**e2-standard-4 / 16GB**) |
| VM Qdrant | `qdrant-base` (riêng) | **BỎ** — Qdrant in-compose |
| DB | Cloud SQL `vsf-rag-postgres-dev` PG18 | **BỎ Cloud SQL** → Postgres in-compose trên VM |
| GCS | `vsf-rag-chatbot-docs-dev` | `…-dev2`, lifecycle xóa file >90 ngày |
| Vùng | asia-southeast1 | asia-southeast1 (giữ) |

Gộp 2 VM → 1 **và** bỏ Cloud SQL là hai khoản tiết kiệm lớn nhất. Đổi lại VM phải
to hơn (16GB) vì nay gánh thêm Postgres app + Qdrant + Langfuse.

> ⚠ **Cần đổi app-side**: thêm container `app-postgres` vào `docker-compose.yml` và
> trỏ `DATABASE_URL` của các service (rag/user/doc/hr) về `app-postgres:5432` thay
> vì Cloud SQL. Các DB cần tạo: `rag_db`, `user_db`, `doc_db`, `hr_db`. Đây là việc
> chưa làm trong các file env hiện tại (vẫn trỏ Cloud SQL).

## 6 guardrail (script `dev-provision.sh` tự set 5, 1 làm tay)

| # | Guardrail | Chặn cái gì |
|---|---|---|
| 1 | Billing account OPEN | Không lặp lại cái chết "hết credit trial" |
| 2 | VM right-size, no GPU, disk trần 40GB | Không lỡ tay máy to / GPU đắt |
| 3 | **Auto-shutdown** T2-T6 08:00–20:00 | Cắt ~64% giờ chạy → giảm tiền compute mạnh nhất |
| 4 | **Không Cloud SQL** (Postgres in-compose) | Bỏ hẳn 1 dòng tiền managed; data trong disk VM |
| 5 | Budget alert $30 (50/90/100%) | Cảnh báo sớm, không tự tắt (giữ uptime) |
| 6 | **Quota CPU=4, GPU=0** (làm tay ở Console) | Trần cứng: không tài nguyên nào vượt nổi |

## Ước tính chi phí (asia-southeast1, ~)

| Hạng mục | On-demand 24/7 | **Có auto-shutdown** (264h/tháng) |
|---|---|---|
| VM e2-standard-4 (16GB) | ~$108 | ~$38 |
| Disk 40GB pd-balanced | ~$4 | ~$4 |
| GCS + egress | ~$1–2 | ~$1–2 |
| **Tổng** | **~$113** | **~$44** |

VM to hơn (16GB) đẩy chi phí lên ~$44 dù đã auto-shutdown. Để về ~$30:
- bật `USE_SPOT="true"` (VM ~1/3 giá → tổng ~$20, đổi lại có thể bị preempt), **hoặc**
- hạ `VM_MACHINE="e2-standard-2"` (8GB) + thêm swap nếu chịu được rủi ro OOM khi ingest.

> Bỏ Cloud SQL tiết kiệm ~$9/tháng nhưng **rủi ro mất data nếu mất VM** — nên
> cron `pg_dump` đẩy lên GCS để backup (chi phí ~0).

## Chạy

```bash
# 1. Sửa CONFIG đầu file (PROJECT_ID, GCS_BUCKET phải duy nhất toàn GCP)
bash infra/gcp/dev-provision.sh
# 2. SSH vào VM rồi chạy bootstrap Docker
gcloud compute ssh vsf-rag-demo-vm --zone=asia-southeast1-a
#    (trên VM) bash infra/gcp/gce-setup.sh
```

Sau đó đặt `deploy/secrets/gcp-sa.json`, điền `deploy/env/*.env`, `docker compose up -d`.
