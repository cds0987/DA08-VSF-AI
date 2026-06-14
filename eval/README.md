# Phase 1.5 Eval Guide

Folder `eval/` chay checkpoint Phase 1.5 cho RAG chatbot. Co 2 luong:

- `Local Docker Eval`: dung stack local/Docker, co upload dataset vao local infra.
- `Production VM Read-Only Eval`: dung VM production tren GCP, khong upload/xoa tai lieu production; chi query cac tai lieu da duoc index san.

Tat ca output nam trong:

```text
eval/output/<timestamp>-<dataset>/
```

## Production VM Read-Only Eval

Dung luong nay khi team da host app tren GCP Compute Engine va muon test production that.

### Dieu kien bat buoc

- Chay tu repo root.
- Da cai Google Cloud SDK (`gcloud --version` pass).
- Da login GCP:

```powershell
gcloud auth login
```

- VM production dang chay stack app va cac endpoint noi bo tren VM:
  - `http://localhost:8000/health`
  - `http://localhost:8001/health`
  - `http://localhost:8002/health`
  - `http://localhost:8003/health` neu service co health endpoint.
- 6 file trong `eval/dataset/dataset_new` da duoc upload va indexed san tren production:
  - `Bo luat lao dong 2019.pdf` / `Bộ luật lao động 2019.pdf`
  - `CNHC_Employee_Handbook.pdf`
  - `DKT-Employee-Handbook-12.23.pdf`
  - `Employee-Handbook-for-Nonprofits-and-Small-Businesses.pdf`
  - `Mau-noi-quy-lao-dong-2024.docx`
  - `PCI_Employee_Handbook.pdf`

Runner se goi `GET /documents`, match theo ten file, va chi chay neu document co status `indexed`.

### Tao `eval/.env.production`

Copy file mau:

```powershell
Copy-Item eval\.env.production.example eval\.env.production
notepad eval\.env.production
```

Dien cac bien chinh:

```env
GCP_PROJECT_ID=<project-id>
GCP_VM_NAME=<vm-name>
GCP_ZONE=<zone>
REMOTE_EVAL_DIR=/tmp/vsf-eval
PROD_APP_DIR=/home/<vm-user>/<repo-dir>

USER_URL=http://localhost:8000
QUERY_URL=http://localhost:8001
DOC_URL=http://localhost:8002
MCP_URL=http://localhost:8003

SEED_ADMIN_EMAIL=<admin-email>
SEED_ADMIN_PASSWORD=<admin-password>
OPENAI_API_KEY=<openai-key-for-ragas>

EVAL_PRODUCTION_READONLY=true
EVAL_REQUIRE_INDEXED_DOCS=true
```

Lay thong tin GCP:

- `GCP_PROJECT_ID`: Google Cloud Console -> project selector.
- `GCP_VM_NAME`, `GCP_ZONE`: Compute Engine -> VM instances -> dong VM dang host app.
- `PROD_APP_DIR`: thu muc repo tren VM, hoi DevOps neu khong chac.

Lay key/secret:

- `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`: hoi DevOps hoac lay tu Secret Manager neu team dang luu admin seed tai do.
- `OPENAI_API_KEY`: lay tu Secret Manager hoac OpenAI dashboard. Key nay dung cho RAGAS evaluator, khong commit.
- Neu VM bat internal MCP token/JWT custom, dien them `MCP_INTERNAL_TOKEN`, `JWT_SECRET_KEY`.

`eval/.env.production` da duoc ignore. Khong commit file nay.

### Lenh production chuan

Smoke nhanh 1 cau, 1 request:

```powershell
.\eval\run_production_eval.ps1 -Smoke
```

Checkpoint Phase 1.5 mac dinh: `dataset_new`, 30 cau, RAGAS day du, 50 concurrent users nhung performance duration mac dinh = 0 de khong keo dai:

```powershell
.\eval\run_production_eval.ps1
```

Stress nhanh 50 concurrent users, 100 request, bo RAGAS de tiet kiem thoi gian/token:

```powershell
.\eval\run_production_eval.ps1 -Stress -Concurrency 50
```

Checkpoint co sample cap ro rang:

```powershell
.\eval\run_production_eval.ps1 -Limit 30 -Concurrency 50 -PerfSamples 100
```

Sau khi chay xong, script copy remote output ve local `eval/output`.

### Output production can co

Mot run production thanh cong phai co:

- `manifest.json`
- `preflight.json`
- `preflight_diagnostics.json`
- `auth.json`
- `production_document_map.json`
- `upload_map.json` (compat artifact, chua document_id production da match)
- `ingest_status.json` (mode `production_readonly`)
- `golden_qa_used.jsonl`
- `qa_results.jsonl`
- `retrieval_results.jsonl`
- `ragas_results.jsonl`
- `ragas_summary.json`
- `safety_reliability.json`
- `performance_cold.json`
- `business_metrics.json`
- `decision.json`
- `metrics_summary.json`
- `report.md`

### Production safety notes

- Runner khong upload/xoa tai lieu production khi `production_readonly=true`.
- Runner co gui query va synthetic feedback de do business metrics theo plan.
- ACL metric se `not_run` neu production khong co restricted document/account setup san cho eval; decision se fail metric nay thay vi gia pass.
- Neu `production_document_map.json` bao missing/unready, hay upload/index cac file dataset tren Admin UI truoc roi chay lai.

## Local Docker Eval

Dung khi can test local voi Docker. Luong local cu duoc giu nguyen.

### Quick start local

```powershell
cd D:\DA08-VSF-AI
.\eval\run_local_eval.ps1 -Smoke -Concurrency 1
```

Lan dau can:

- Python 3.11+.
- Docker Desktop da mo va `docker version` pass.
- Repo-root `.env` co it nhat:

```env
OPENAI_API_KEY=sk-...
```

Mac dinh local runner tu dung MinIO + Qdrant local qua `eval/docker-compose.local-eval.yml`.

### Lenh local hay dung

Checkpoint day du:

```powershell
.\eval\run_local_eval.ps1
```

Checkpoint 30 cau, 5 concurrent users:

```powershell
.\eval\run_local_eval.ps1 -Dataset dataset_new -Limit 30 -Concurrency 5
```

Smoke nhanh:

```powershell
.\eval\run_local_eval.ps1 -Smoke -Concurrency 1 -SkipBuild
```

Warm-cache performance rieng:

```powershell
.\eval\run_local_eval.ps1 -WarmCache
```

## Metrics Phase 1.5

Runner tao report cho 4 nhom trong `docs/roadmap.md`:

- RAG Quality: Faithfulness, Answer Relevancy, Context Precision, Context Recall, Answer Correctness.
- Performance: first token latency p95, response latency p95, concurrent users.
- Safety & Reliability: hallucination rate, graceful rejection rate, access control accuracy.
- Business Metrics: feedback rate/synthetic satisfaction, answerable rate, top questions/admin metrics.

Nguong pass/fail nam trong `eval/lib/metrics.py`.

## Troubleshooting

PowerShell chan script:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Kiem tra VM bang tay:

```powershell
gcloud compute ssh <vm-name> --zone=<zone> --tunnel-through-iap --command "cd <prod-app-dir> && sudo docker compose ps"
```

Preflight fail:

- Kiem tra `GCP_PROJECT_ID`, `GCP_VM_NAME`, `GCP_ZONE`.
- Kiem tra `PROD_APP_DIR`.
- SSH vao VM va chay `curl -f http://localhost:8000/health`, `8001`, `8002`.

Production missing document:

- Mo Admin UI tren production.
- Upload 6 file trong `eval/dataset/dataset_new`.
- Doi status `indexed`.
- Chay lai `.\eval\run_production_eval.ps1 -Smoke`.

Doc discovery debug:

- Mo `eval/output/<latest>/production_document_map.json`.
- Xem `missing`, `duplicate_matches`, `upload_map`.

Local Docker fail:

```powershell
docker version
docker compose version
```

Neu Docker daemon chua san sang, mo Docker Desktop va chay lai.
