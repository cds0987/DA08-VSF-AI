#!/usr/bin/env python3
"""
NATS JetStream provisioner — NGUỒN DUY NHẤT tạo/đồng bộ stream theo contract
infra/nats/subjects.md. Chạy MỘT LẦN lúc deploy (one-shot nats-bootstrap), TRƯỚC
khi service kết nối -> mọi service verify-only, hết cảnh nhiều app đua add_stream
vào cùng broker gây "subjects overlap".

Dùng nats-py (đã có trong image rag-worker) thay vì nats CLI -> không phụ thuộc cú
pháp/flag theo version. Idempotent: chạy lại vô hại. KIÊM migration: xóa stream
legacy DOCS (deviation cũ của rag-worker) đè subject của DOC_EVENTS.

Exit 0 = OK; exit 1 = lỗi (deploy fail-closed -> rollback).
ENV: NATS_URL (mặc định nats://nats:4222).
"""
from __future__ import annotations

import asyncio
import os
import sys

import nats
from nats.js.api import DiscardPolicy, RetentionPolicy, StorageType, StreamConfig

NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")

# Theo infra/nats/subjects.md (DevOps contract).
STREAMS = [
    ("DOC_EVENTS", ["doc.ingest", "doc.status", "doc.access"]),
    ("NOTIFY_EVENTS", ["notify.doc_new"]),
    ("HR_EVENTS", ["hr.*", "hr.employee_profile.updated"]),
]
LEGACY_STREAMS = ["DOCS"]  # migrate: xóa stream cũ đè subject của DOC_EVENTS


async def _connect():
    last = None
    for attempt in range(1, 61):
        try:
            nc = await nats.connect(NATS_URL, connect_timeout=5, max_reconnect_attempts=1)
            print(f"[bootstrap] connected to {NATS_URL} (attempt {attempt})", flush=True)
            return nc
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"[bootstrap] chờ NATS ({attempt}/60): {exc}", flush=True)
            await asyncio.sleep(2)
    raise RuntimeError(f"NATS không sẵn sàng sau ~120s: {last}")


async def _main() -> int:
    nc = await _connect()
    js = nc.jetstream()
    try:
        # MIGRATION: xóa stream legacy đè subject của DOC_EVENTS.
        for name in LEGACY_STREAMS:
            try:
                await js.stream_info(name)
            except Exception:
                continue  # không tồn tại -> bỏ qua
            await js.delete_stream(name)
            print(f"[bootstrap] migration: đã xóa stream legacy {name}", flush=True)

        # Provision stream chuẩn (idempotent).
        for name, subjects in STREAMS:
            try:
                await js.stream_info(name)
                print(f"[bootstrap] stream {name} đã tồn tại -> giữ nguyên", flush=True)
                continue
            except Exception:
                pass
            try:
                await js.add_stream(
                    StreamConfig(
                        name=name,
                        subjects=subjects,
                        retention=RetentionPolicy.LIMITS,
                        storage=StorageType.FILE,
                        discard=DiscardPolicy.OLD,
                        num_replicas=1,
                    )
                )
                print(f"[bootstrap] đã tạo stream {name} {subjects}", flush=True)
            except Exception as exc:  # noqa: BLE001
                # 10065 = subjects overlap: subject ĐÃ được stream khác (owner khác,
                # vd hr-service) provision rồi -> coi như đã có, KHÔNG fail. Migration
                # xóa DOCS ở trên đã đảm bảo doc.* không bị stream lạ chiếm.
                msg = str(exc)
                if "10065" in msg or "overlap" in msg.lower() or "in use" in msg.lower():
                    print(
                        f"[bootstrap] {name}: subject đã được stream khác sở hữu -> bỏ qua ({msg})",
                        flush=True,
                    )
                    continue
                raise

        print("[bootstrap] NATS bootstrap DONE", flush=True)
        return 0
    finally:
        await nc.drain()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(_main()))
    except Exception as exc:  # noqa: BLE001
        print(f"[bootstrap] FAILED: {exc}", flush=True)
        sys.exit(1)
