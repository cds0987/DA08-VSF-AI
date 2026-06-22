#!/usr/bin/env python3
"""
Investigate 'NỘI QUY VĂN PHÒNG CÔNG TY' retrieval issues.

Steps:
  1. Run 2 new questions standalone (no context)
  2. Run same 2 questions with context (Q1 → Q2 → new Qs)
  3. List documents, find nội quy văn phòng doc IDs
  4. Probe document structure via targeted rag_search with doc_ids filter
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

NEW_QUESTIONS = [
    "cho tôi thêm thông tin về nội quy văn phòng công ty",
    "không thể tìm được thông tin về Giờ làm việc cụ thể trong tài liệu Nội quy văn phòng công ty à",
]

CONTEXT_SEED = "Công ty mình có các quy định nội bộ gì"

PROBE_QUERIES = [
    "giờ làm việc",
    "thời gian làm việc",
    "mục I",
    "quy định chung",
    "điều khoản",
    "trang phục",
    "nghỉ phép",
]


def _sep(char="─", width=80):
    print(char * width)


async def login(client: httpx.AsyncClient) -> tuple[str, str]:
    resp = await client.post(f"{USER_SERVICE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    me = await client.get(f"{USER_SERVICE}/auth/me", headers={"Authorization": f"Bearer {token}"})
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


async def ask(
    client: httpx.AsyncClient,
    token: str,
    user_id: str,
    question: str,
    label: str,
    conversation_id: str | None = None,
    trace_session: str = "debug-noiquy",
    document_ids: list[str] | None = None,
) -> tuple[list[dict], str | None]:
    """Returns (key_events, conversation_id_from_response)."""
    conv_id = conversation_id or str(uuid.uuid4())
    _sep("═")
    print(f"[{label}]  conv={conv_id[:8]}...")
    print(f"Q: {question}")
    _sep()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    body: dict = {
        "question": question,
        "user_id": user_id,
        "conversation_id": conv_id,
        "trace_session": trace_session,
    }
    if document_ids:
        body["document_ids"] = document_ids

    answer_parts: list[str] = []
    key_events: list[dict] = []

    async with client.stream("POST", f"{QUERY_SERVICE}/query", headers=headers, json=body,
                              timeout=httpx.Timeout(60, connect=10)) as resp:
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code}: {(await resp.aread()).decode()[:300]}")
            return key_events, conv_id

        buffer = ""
        try:
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    packet, buffer = buffer.split("\n\n", 1)
                    for event in parse_sse(packet + "\n\n"):
                        phase = event.get("phase")
                        if phase == "acting":
                            args = event.get("tool_args", {})
                            tool = event.get("tool", "")
                            print(f"  [ACTING]  tool={tool}  args={json.dumps(args, ensure_ascii=False)}")
                            key_events.append({"phase": "acting", "tool": tool, "args": args})
                        elif phase == "observing":
                            summary = event.get("tool_result_summary", {})
                            print(f"  [OBSERVE] {json.dumps(summary, ensure_ascii=False)}")
                            key_events.append({"phase": "observing", "summary": summary})
                        elif phase in ("thinking", "planning"):
                            msg = event.get("message") or ""
                            if msg:
                                print(f"  [{phase.upper():<8}] {str(msg)[:100]}")
                        token_val = event.get("token")
                        if token_val:
                            answer_parts.append(str(token_val))
                        if event.get("done"):
                            outcome = event.get("outcome")
                            sources = event.get("sources", [])
                            print(f"  [DONE]    outcome={outcome}  sources={len(sources)}")
                            for s in sources[:5]:
                                doc = s.get("document_name", "")
                                score = s.get("score", 0)
                                heading = s.get("heading_path", [])
                                print(f"    • {doc} | score={score:.3f} | heading={heading}")
                            key_events.append({"phase": "done", "outcome": outcome, "sources": sources})
        except (httpx.RemoteProtocolError, httpx.ReadError) as exc:
            print(f"  [STREAM CUT] {exc} (buffered {len(answer_parts)} tokens)")

    _sep("-")
    answer = "".join(answer_parts)
    print(f"  ANSWER: {answer[:600]}")
    _sep()
    return key_events, conv_id


async def list_documents(client: httpx.AsyncClient, token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    docs = []
    for url in [f"{DOC_SERVICE}/", f"{DOC_SERVICE}/documents", DOC_SERVICE]:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for key in ("documents", "data", "items", "results"):
                        if isinstance(data.get(key), list):
                            return data[key]
        except Exception:
            continue
    return docs


def find_noiquy_docs(docs: list[dict]) -> list[str]:
    keywords = ["nội quy văn phòng", "noi quy van phong", "noiquy"]
    ids = []
    for d in docs:
        name = (d.get("name") or d.get("file_name") or d.get("document_name") or "").lower()
        if any(k in name for k in keywords) or any(
            k in (d.get("id") or "").lower() for k in keywords
        ):
            ids.append(d.get("id") or d.get("document_id") or "")
            print(f"  → Found: {d.get('name') or d.get('file_name')} (id={d.get('id') or d.get('document_id')})")
    return [i for i in ids if i]


async def probe_doc_structure(
    client: httpx.AsyncClient,
    token: str,
    user_id: str,
    doc_ids: list[str],
):
    """Send targeted queries with document_ids filter to map the indexed content."""
    _sep("═")
    print(f"=== DOCUMENT STRUCTURE PROBE (doc_ids={doc_ids}) ===")
    _sep()

    seen_headings: dict[str, list[str]] = {}  # doc_name → [headings]

    for query in PROBE_QUERIES:
        conv_id = str(uuid.uuid4())
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        body = {
            "question": query,
            "user_id": user_id,
            "conversation_id": conv_id,
            "trace_session": "debug-probe",
            "document_ids": doc_ids,
        }
        print(f"\n  probe query: '{query}'")
        async with client.stream("POST", f"{QUERY_SERVICE}/query", headers=headers, json=body,
                                  timeout=httpx.Timeout(45, connect=10)) as resp:
            if resp.status_code != 200:
                print(f"    HTTP {resp.status_code}")
                continue
            buffer = ""
            try:
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        packet, buffer = buffer.split("\n\n", 1)
                        for event in parse_sse(packet + "\n\n"):
                            if event.get("done"):
                                sources = event.get("sources", [])
                                if not sources:
                                    print(f"    → 0 sources")
                                for s in sources:
                                    doc = s.get("document_name", "?")
                                    heading = s.get("heading_path", [])
                                    score = s.get("score", 0)
                                    print(f"    → [{doc}] score={score:.3f}  heading={heading}")
                                    if doc not in seen_headings:
                                        seen_headings[doc] = []
                                    for h in heading:
                                        if h not in seen_headings[doc]:
                                            seen_headings[doc].append(h)
            except (httpx.RemoteProtocolError, httpx.ReadError) as exc:
                print(f"    [STREAM CUT] {exc}")
        await asyncio.sleep(1.5)

    print("\n=== HEADING SUMMARY PER DOCUMENT ===")
    for doc, headings in seen_headings.items():
        print(f"\n  [{doc}]")
        for h in headings:
            print(f"    - {h}")


async def main():
    timeout = httpx.Timeout(120, connect=10)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        token, user_id = await login(client)
        print(f"Logged in: user_id={user_id}\n")

        # ── Part 1: Standalone (no context) ──────────────────────────────────
        print("\n" + "█" * 80)
        print("PART 1: STANDALONE (no prior context)")
        print("█" * 80)
        for i, q in enumerate(NEW_QUESTIONS, 1):
            await ask(client, token, user_id, q, f"STANDALONE-Q{i}")
            await asyncio.sleep(2)

        # ── Part 2: With context (seed → new Qs) ─────────────────────────────
        print("\n" + "█" * 80)
        print("PART 2: WITH CONTEXT (seed Q first)")
        print("█" * 80)
        conv_id = str(uuid.uuid4())
        await ask(client, token, user_id, CONTEXT_SEED, "CTX-SEED", conversation_id=conv_id)
        await asyncio.sleep(2)
        for i, q in enumerate(NEW_QUESTIONS, 1):
            await ask(client, token, user_id, q, f"CTX-Q{i}", conversation_id=conv_id)
            await asyncio.sleep(2)

        # ── Part 3: Document list + structure probe ───────────────────────────
        print("\n" + "█" * 80)
        print("PART 3: DOCUMENT STRUCTURE PROBE")
        print("█" * 80)
        docs = await list_documents(client, token)
        print(f"\nTotal documents: {len(docs)}")
        for d in docs[:20]:
            name = d.get("name") or d.get("file_name") or d.get("document_name") or ""
            doc_id = d.get("id") or d.get("document_id") or ""
            print(f"  {doc_id[:16]}... | {name}")

        print("\nSearching for 'Nội quy văn phòng' documents:")
        noiquy_ids = find_noiquy_docs(docs)

        # Fallback: even if not found by name, probe with q_000XXX.jpg doc IDs we saw
        # from previous test (q_000004, q_000009, q_000012, q_000024, q_000025)
        if noiquy_ids:
            await probe_doc_structure(client, token, user_id, noiquy_ids)
        else:
            print("  → Could not find by name. Probing via query without doc_ids filter.")
            await probe_doc_structure(client, token, user_id, [])


if __name__ == "__main__":
    asyncio.run(main())
