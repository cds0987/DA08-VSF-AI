#!/usr/bin/env python3
"""
CI smoke: Langfuse self-host SẴN SÀNG nhận data chưa + dọn sạch sau test.

Langfuse v2 KHÔNG có public API xóa trace (chỉ từ v3) -> việc XÓA do workflow làm
trực tiếp ở tầng Postgres (CI làm chủ container DB), script chỉ lo phần HTTP:

  ingest          : POST /api/public/ingestion -> tạo trace -> poll GET tới khi hiện
                    ra (chứng minh Langfuse NHẬN + xử lý data). Trace id = $SMOKE_TRACE_ID.
  confirm-deleted : GET /api/public/traces/{id} -> phải 404 (xác nhận đã bị xóa sạch).

Chạy fail-closed (exit != 0 nếu sai) — giống các validate khác.

ENV: LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, SMOKE_TRACE_ID
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
TRACE_ID = os.environ["SMOKE_TRACE_ID"]
TIMEOUT = 15


def ingest() -> None:
    payload = {
        "batch": [
            {
                "id": str(uuid.uuid4()),
                "type": "trace-create",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "body": {
                    "id": TRACE_ID,
                    "name": "ci-langfuse-smoke",
                    "userId": "ci",
                    "metadata": {"source": "ci_langfuse.py"},
                },
            }
        ]
    }
    r = requests.post(f"{HOST}/api/public/ingestion", json=payload, auth=AUTH, timeout=TIMEOUT)
    if r.status_code not in (200, 201, 207):
        print(f"  FAIL ingestion: HTTP {r.status_code} {r.text[:300]}")
        sys.exit(1)
    print(f"  ingestion OK (HTTP {r.status_code})")

    for i in range(1, 31):
        g = requests.get(f"{HOST}/api/public/traces/{TRACE_ID}", auth=AUTH, timeout=TIMEOUT)
        if g.status_code == 200:
            print(f"  trace hiện ra sau {i} lần poll -> Langfuse NHẬN DATA OK")
            return
        time.sleep(2)
    print("  FAIL: trace không xuất hiện (ingestion treo / DB lỗi?)")
    sys.exit(1)


def confirm_deleted() -> None:
    for _ in range(15):
        g = requests.get(f"{HOST}/api/public/traces/{TRACE_ID}", auth=AUTH, timeout=TIMEOUT)
        if g.status_code == 404:
            print("  xác nhận đã XÓA (GET -> 404) -> không để lại rác")
            return
        time.sleep(2)
    print("  FAIL: trace vẫn còn sau khi xóa")
    sys.exit(1)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    print(f"== Langfuse smoke [{cmd}] (trace_id={TRACE_ID}) ==")
    if cmd == "ingest":
        ingest()
    elif cmd == "confirm-deleted":
        confirm_deleted()
    else:
        print("usage: ci_langfuse.py <ingest|confirm-deleted>")
        sys.exit(2)


if __name__ == "__main__":
    main()
