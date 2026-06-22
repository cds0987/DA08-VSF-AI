#!/usr/bin/env python3
"""
Deep probe: tại sao q_000004 có 'thời gian làm việc' nhưng Q1 không lấy được?
- Liệt kê tất cả documents, tìm document_id chứa q_000004.jpg và q_000025.jpg
- Probe document đó với nhiều query khác nhau, xem ranking của từng chunk
- So sánh scores: query về "nội quy văn phòng" vs query về "thời gian làm việc"
"""
from __future__ import annotations

import asyncio
import io
import json
import uuid
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = "https://vsfchat.cloud"
EMAIL = "admin@company.com"
PASSWORD = "DemoAdminPassword123!"
USER_SERVICE = f"{BASE}/api/user"
QUERY_SERVICE = f"{BASE}/api/query"
DOC_SERVICE = f"{BASE}/api/documents"


def _sep(char="─", width=80):
    print(char * width)


async def login(client: httpx.AsyncClient) -> tuple[str, str]:
    resp = await client.post(f"{USER_SERVICE}/auth/login",
                              json={"email": EMAIL, "password": PASSWORD})
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    me = await client.get(f"{USER_SERVICE}/auth/me",
                           headers={"Authorization": f"Bearer {token}"})
    me.raise_for_status()
    return token, me.json()["id"]


def parse_sse(text: str) -> list[dict]:
    events = []
    for packet in text.split("\n\n"):
        for line in packet.strip().splitlines():
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass
    return events


async def list_all_documents(client: httpx.AsyncClient, token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    for url in [f"{DOC_SERVICE}/", f"{DOC_SERVICE}/documents", DOC_SERVICE]:
        try:
            resp = await client.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                for key in ("documents", "data", "items", "results"):
                    if isinstance(data.get(key), list):
                        return data[key]
        except Exception as e:
            print(f"  [doc list error] {url}: {e}")
    return []


async def query_with_doc_ids(
    client: httpx.AsyncClient,
    token: str,
    user_id: str,
    question: str,
    doc_ids: list[str] | None,
    label: str,
    top_k_hint: str = "",
) -> list[dict]:
    """Run a query and return all sources with scores."""
    _sep()
    target = f"doc_ids={doc_ids}" if doc_ids else "ALL docs"
    print(f"  [{label}] Q: '{question}'  target={target} {top_k_hint}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    body: dict = {
        "question": question,
        "user_id": user_id,
        "conversation_id": str(uuid.uuid4()),
        "trace_session": "debug-q4probe",
    }
    if doc_ids is not None:
        body["document_ids"] = doc_ids

    all_sources: list[dict] = []
    answer_parts: list[str] = []

    try:
        async with client.stream(
            "POST", f"{QUERY_SERVICE}/query",
            headers=headers, json=body,
            timeout=httpx.Timeout(90, connect=10),
        ) as resp:
            if resp.status_code != 200:
                raw = (await resp.aread()).decode()
                print(f"    HTTP {resp.status_code}: {raw[:200]}")
                return []

            buffer = ""
            try:
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        packet, buffer = buffer.split("\n\n", 1)
                        for ev in parse_sse(packet + "\n\n"):
                            ph = ev.get("phase")
                            if ph == "acting":
                                args = ev.get("tool_args", {})
                                print(f"    [ACTING] tool={ev.get('tool')}  query='{args.get('query', '')}'")
                            elif ph == "observing":
                                s = ev.get("tool_result_summary", {})
                                print(f"    [OBSERVE] count={s.get('count')}  docs={s.get('docs')}")
                            t = ev.get("token")
                            if t:
                                answer_parts.append(str(t))
                            if ev.get("done"):
                                srcs = ev.get("sources", [])
                                all_sources = srcs
                                outcome = ev.get("outcome")
                                print(f"    [DONE] outcome={outcome}  sources={len(srcs)}")
                                for s in srcs:
                                    doc = s.get("document_name", "?")
                                    sc = s.get("score", 0)
                                    hp = s.get("heading_path", [])
                                    cap = s.get("caption", "")[:80]
                                    print(f"      • {doc} | score={sc:.3f} | heading={hp}")
                                    print(f"        caption: {cap}")
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout) as e:
                print(f"    [STREAM CUT] {type(e).__name__}: {e}")
    except Exception as e:
        print(f"    [ERROR] {type(e).__name__}: {e}")

    if answer_parts:
        ans = "".join(answer_parts)
        print(f"    ANSWER: {ans[:300]}")

    return all_sources


async def main():
    timeout = httpx.Timeout(120, connect=10)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        token, user_id = await login(client)
        print(f"Logged in: user_id={user_id}")

        # ── Step 1: List all documents ─────────────────────────────────────
        _sep("═")
        print("STEP 1: LIST ALL DOCUMENTS")
        _sep("═")
        docs = await list_all_documents(client, token)
        print(f"Total documents returned: {len(docs)}")

        q4_doc_id = None
        q25_doc_id = None
        all_doc_ids = []

        for d in docs:
            name = (d.get("name") or d.get("file_name") or
                    d.get("document_name") or d.get("title") or "")
            doc_id = str(d.get("id") or d.get("document_id") or "")
            all_doc_ids.append(doc_id)
            print(f"  id={doc_id[:20]:<22} name={name}")
            if "q_000004" in name or "000004" in doc_id:
                q4_doc_id = doc_id
                print(f"    ↑ FOUND q_000004 doc (id={doc_id})")
            if "q_000025" in name or "000025" in doc_id:
                q25_doc_id = doc_id
                print(f"    ↑ FOUND q_000025 doc (id={doc_id})")

        # ── Step 2: Probe q_000004's document specifically ─────────────────
        _sep("═")
        print("STEP 2: PROBE q_000004 DOCUMENT WITH MULTIPLE QUERIES")
        print("(Shows ranking: why does 'thời gian làm việc' content score low?)")
        _sep("═")

        q4_ids = [q4_doc_id] if q4_doc_id else None

        probe_qs = [
            ("nội quy văn phòng công ty",
             "← Q1's actual query (what was retrieved in Q1)"),
            ("thời gian làm việc giờ làm việc",
             "← content-specific query (should score high for TG chunk)"),
            ("thời gian làm việc trong nội quy văn phòng công ty",
             "← combined query"),
            ("8h sáng 5h chiều giờ làm việc",
             "← explicit keywords về giờ"),
            ("trang phục quy định văn phòng",
             "← another section as comparison"),
            ("quy định chung phạm vi áp dụng",
             "← intro section"),
        ]

        print(f"\nTarget document_ids: {q4_ids}\n")
        for q, note in probe_qs:
            await query_with_doc_ids(client, token, user_id, q, q4_ids, note)
            await asyncio.sleep(2)

        # ── Step 3: Cross-compare — same queries against q_000025's doc ────
        if q25_doc_id and q25_doc_id != q4_doc_id:
            _sep("═")
            print("STEP 3: SAME QUERIES AGAINST q_000025 DOCUMENT")
            _sep("═")
            q25_ids = [q25_doc_id]
            for q, note in probe_qs[:3]:
                await query_with_doc_ids(
                    client, token, user_id, q, q25_ids,
                    f"q25: {note}")
                await asyncio.sleep(2)
        else:
            # Fallback: run without doc filter to see ranking across all
            _sep("═")
            print("STEP 3: CROSS-DOC COMPARISON (no doc filter) — top-5 by score")
            _sep("═")
            cross_qs = [
                "thời gian làm việc giờ làm việc",
                "nội quy văn phòng công ty",
            ]
            for q, note in zip(cross_qs, ["content query", "title query"]):
                await query_with_doc_ids(client, token, user_id, q, None, note)
                await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
