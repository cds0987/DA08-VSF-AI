# Production VM Eval Notes

Huong dan chinh nam trong `eval/README.md`, muc **Production VM Read-Only Eval**. File nay chi la checklist nhanh khi can test tren VM.

## Source of Truth

Khong hardcode project/VM/path trong lenh nua. Dien tat ca vao:

```powershell
eval\.env.production
```

Tao tu file mau:

```powershell
Copy-Item eval\.env.production.example eval\.env.production
notepad eval\.env.production
```

Bien quan trong:

- `GCP_PROJECT_ID`
- `GCP_VM_NAME`
- `GCP_ZONE`
- `REMOTE_EVAL_DIR=/tmp/vsf-eval`
- `PROD_APP_DIR=<repo dir tren VM>`
- `SEED_ADMIN_EMAIL`
- `SEED_ADMIN_PASSWORD`
- `OPENAI_API_KEY`
- `EVAL_PRODUCTION_READONLY=true`
- `EVAL_REQUIRE_INDEXED_DOCS=true`

## Read-Only Production Rule

Production eval khong upload/xoa tai lieu. Truoc khi chay, production phai co san 6 file trong `eval/dataset/dataset_new` va status phai la `indexed`.

Runner se:

1. SSH vao VM bang `gcloud`.
2. Copy rieng code/dataset eval len `REMOTE_EVAL_DIR`.
3. Tao venv va cai `eval/requirements.txt`.
4. Login admin.
5. Goi `GET /documents` de match ten file dataset voi document production da indexed.
6. Chay query/RAGAS/performance/safety/business metrics.
7. Copy output ve local `eval/output`.

## Commands

Smoke:

```powershell
.\eval\run_production_eval.ps1 -Smoke
```

Checkpoint:

```powershell
.\eval\run_production_eval.ps1
```

Stress nhanh:

```powershell
.\eval\run_production_eval.ps1 -Stress -Concurrency 50
```

## Debug

Kiem tra VM:

```powershell
gcloud compute ssh $env:GCP_VM_NAME --zone=$env:GCP_ZONE --tunnel-through-iap --command "cd $env:PROD_APP_DIR && sudo docker compose ps"
```

Neu production document map fail, doc output moi nhat:

```powershell
Get-ChildItem eval\output -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

Mo:

```text
production_document_map.json
```
