#!/usr/bin/env python3
"""
CI smoke: Langfuse sẵn sàng NHẬN DATA chưa.

Luồng (giống các validate khác — fail-closed, exit != 0 nếu hỏng):
  1) POST /api/public/ingestion  -> tạo 1 trace test (basic auth = public:secret key).
  2) Poll GET /api/public/traces/{id} -> chờ ingestion xử lý xong (trace hiện ra).
  3) DELETE /api/public/traces (bulk) -> XÓA NGAY trace test vừa tạo.
  4) GET lại -> phải 404 (xác nhận đã xóa, không để rác).

ENV:
  LANGFUSE_HOST        (vd http://localhost:3000)
  LANGFUSE_PUBLIC_KEY  (pk-lf-...)
  LANGFUSE_SECRET_KEY  (sk-lf-...)
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timezone

import requests

HOST = os.environ["LANGFUSE_HOST"].rstrip("/")
AUTH = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
TIMEOUT = 15


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ingest_trace(trace_id: str) -> None:
    payload = {
        "batch": [
            {
                "id": str(uuid.uuid4()),
                "type": "trace-create",
                "timestamp": _now(),
                "body": {
                    "id": trace_id,
                    "name": "ci-langfuse-smoke",
                    "userId": "ci",
                    "metadata": {"source": "ci_langfuse.py"},
                },
            }
        ]
    }
    r = requests.post(f"{HOST}/api/public/ingestion", json=payload, auth=AUTH, timeout=TIMEOUT)
    # 207 Multi-Status = batch nhận; 200/201 cũng coi như OK.
    if r.status_code not in (200, 201, 207):
        print(f"  FAIL ingestion: HTTP {r.status_code} {r.text[:300]}")
        sys.exit(1)
    print(f"  ingestion OK (HTTP {r.status_code})")


def wait_trace(trace_id: str, retries: int = 30) -> None:
    for i in range(1, retries + 1):
        r = requests.get(f"{HOST}/api/public/traces/{trace_id}", auth=AUTH, timeout=TIMEOUT)
        if r.status_code == 200:
            print(f"  trace hiện ra sau {i} lần poll -> Langfuse NHẬN DATA OK")
            return
        time.sleep(2)
    print("  FAIL: trace không xuất hiện (ingestion treo / DB lỗi?)")
    sys.exit(1)


def delete_trace(trace_id: str) -> None:
    # Bulk delete (rộng tương thích hơn DELETE /traces/{id}).
    r = requests.delete(
        f"{HOST}/api/public/traces",
        json={"traceIds": [trace_id]},
        auth=AUTH,
        timeout=TIMEOUT,
    )
    if r.status_code not in (200, 202):
        print(f"  FAIL delete: HTTP {r.status_code} {r.text[:300]}")
        sys.exit(1)
    print(f"  delete OK (HTTP {r.status_code})")


def confirm_deleted(trace_id: str, retries: int = 15) -> None:
    for _ in range(retries):
        r = requests.get(f"{HOST}/api/public/traces/{trace_id}", auth=AUTH, timeout=TIMEOUT)
        if r.status_code == 404:
            print("  xác nhận đã XÓA (GET -> 404) -> không để lại rác")
            return
        time.sleep(2)
    print("  FAIL: trace vẫn còn sau khi xóa")
    sys.exit(1)


def main() -> None:
    trace_id = f"ci-smoke-{uuid.uuid4()}"
    print(f"== Langfuse readiness smoke (trace_id={trace_id}) ==")
    ingest_trace(trace_id)
    wait_trace(trace_id)
    delete_trace(trace_id)
    confirm_deleted(trace_id)
    print("== PASS: Langfuse sẵn sàng nhận data + xóa sạch ==")


if __name__ == "__main__":
    main()
