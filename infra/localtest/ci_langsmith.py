#!/usr/bin/env python3
"""
CI smoke: LangSmith (SaaS cloud) SẴN SÀNG nhận data chưa + dọn sạch sau test.

Khác langfuse (self-host docker): LangSmith là cloud thật -> test ghi vào 1 PROJECT
EPHEMERAL ($SMOKE_PROJECT, duy nhất mỗi run) rồi XÓA NGUYÊN PROJECT (delete_project) —
gọn hơn langfuse (không cần psql). Dùng RunTree low-level y như runtime query-service.

  ingest          : RunTree(chain) + child(llm) -> post/patch -> poll list_runs tới khi
                    hiện ra (chứng minh LangSmith NHẬN + xử lý data).
  purge           : delete_project($SMOKE_PROJECT) -> xóa sạch project test.
  confirm-deleted : has_project($SMOKE_PROJECT) phải False (xác nhận đã xóa).

Fail-closed (exit != 0 nếu sai) — giống ci_langfuse.py.

ENV: LANGSMITH_API_KEY, LANGSMITH_ENDPOINT (mặc định api.smith.langchain.com), SMOKE_PROJECT
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timezone

API_KEY = os.environ["LANGSMITH_API_KEY"]
ENDPOINT = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
PROJECT = os.environ["SMOKE_PROJECT"]


def _client():
    from langsmith import Client

    return Client(api_key=API_KEY, api_url=ENDPOINT)


def ingest() -> None:
    from langsmith.run_trees import RunTree

    client = _client()
    now = datetime.now(timezone.utc)
    run = RunTree(
        name="ci-langsmith-smoke",
        run_type="chain",
        inputs={"question": "ci smoke"},
        project_name=PROJECT,
        client=client,
        extra={"metadata": {"source": "ci_langsmith.py", "marker": str(uuid.uuid4())}},
    )
    run.post()
    child = run.create_child(
        name="llm",
        run_type="llm",
        inputs={"question": "ci smoke"},
        start_time=now,
        extra={"metadata": {"ls_model_name": "gpt-5.4-mini", "ls_provider": "openai"}},
    )
    child.end(outputs={"ok": True}, end_time=datetime.now(timezone.utc))
    child.post()
    run.end(outputs={"ok": True}, end_time=datetime.now(timezone.utc))
    run.patch()
    flush = getattr(client, "flush", None)
    if callable(flush):
        flush()
    print(f"  RunTree posted -> project={PROJECT}")

    # Poll: project + run xuất hiện qua API public (chứng minh LangSmith nhận data).
    for i in range(1, 31):
        try:
            runs = list(client.list_runs(project_name=PROJECT, limit=1))
            if runs:
                print(f"  run hiện ra sau {i} lần poll -> LangSmith NHẬN DATA OK")
                return
        except Exception as exc:  # noqa: BLE001 — project chưa kịp index -> retry
            if i == 1:
                print(f"  (poll {i}: {str(exc)[:120]})")
        time.sleep(2)
    print("  FAIL: run không xuất hiện (ingest treo / project lỗi?)")
    sys.exit(1)


def purge() -> None:
    client = _client()
    try:
        if client.has_project(project_name=PROJECT):
            client.delete_project(project_name=PROJECT)
            print(f"  delete_project({PROJECT}) OK")
        else:
            print(f"  project {PROJECT} không tồn tại -> không cần xóa")
    except Exception as exc:  # noqa: BLE001 — best-effort như langfuse psql delete
        print(f"  WARN purge: {str(exc)[:200]}")


def confirm_deleted() -> None:
    client = _client()
    for _ in range(15):
        if not client.has_project(project_name=PROJECT):
            print("  xác nhận đã XÓA (has_project=False) -> không để lại rác")
            return
        time.sleep(2)
    print("  FAIL: project vẫn còn sau khi xóa")
    sys.exit(1)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    print(f"== LangSmith smoke [{cmd}] (project={PROJECT}) ==")
    if cmd == "ingest":
        ingest()
    elif cmd == "purge":
        purge()
    elif cmd == "confirm-deleted":
        confirm_deleted()
    else:
        print("usage: ci_langsmith.py <ingest|purge|confirm-deleted>")
        sys.exit(2)


if __name__ == "__main__":
    main()
