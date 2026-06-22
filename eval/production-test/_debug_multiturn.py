#!/usr/bin/env python3
"""Ad-hoc debug script: run 5 multi-turn questions, print SSE events to diagnose muc-I/1 bug."""
from __future__ import annotations

import asyncio
import io
import json
import uuid
import sys
from pathlib import Path

import httpx

# Force UTF-8 output so Vietnamese prints correctly on Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = "https://vsfchat.cloud"
EMAIL = "admin@company.com"
PASSWORD = "DemoAdminPassword123!"
USER_SERVICE = f"{BASE}/api/user"
QUERY_SERVICE = f"{BASE}/api/query"

QUESTIONS = [
    "Công ty mình có các quy định nội bộ gì",
    "Cho tôi thêm thông tin về Nội quy văn phòng công ty",
    "Cho tôi thêm thông tin về mục I",
    "tôi thấy trong tài liệu có mục 1 mà không lấy được thông tin à",
    "Thế còn thời gian làm việc ghi trong tài liệu đó thì sao",
]

CONVERSATION_ID = str(uuid.uuid4())


def _sep(char="─", width=80):
    print(char * width)


async def login(client: httpx.AsyncClient) -> tuple[str, str]:
    resp = await client.post(f"{USER_SERVICE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    resp.raise_for_status()
    data = resp.json()
    access_token = data["access_token"]

    me = await client.get(f"{USER_SERVICE}/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    me.raise_for_status()
    user_id = me.json()["id"]
    return access_token, user_id


def parse_sse(text: str) -> list[dict]:
    events = []
    for packet in text.split("\n\n"):
        packet = packet.strip()
        if not packet:
            continue
        for line in packet.splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip()
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
    return events


async def ask(client: httpx.AsyncClient, token: str, user_id: str, question: str, q_num: int):
    _sep("═")
    print(f"[Q{q_num}] {question}")
    _sep()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    body = {
        "question": question,
        "user_id": user_id,
        "conversation_id": CONVERSATION_ID,
        "trace_session": "debug-muc-i",
    }

    buffer = ""
    answer_parts: list[str] = []
    key_events: list[dict] = []

    async with client.stream("POST", f"{QUERY_SERVICE}/query", headers=headers, json=body,
                              timeout=httpx.Timeout(60, connect=10)) as resp:
        if resp.status_code != 200:
            raw = (await resp.aread()).decode()
            print(f"  ✗ HTTP {resp.status_code}: {raw[:300]}")
            return

        async for chunk in resp.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                packet, buffer = buffer.split("\n\n", 1)
                for event in parse_sse(packet + "\n\n"):
                    phase = event.get("phase")
                    if phase == "acting":
                        tool = event.get("tool", "")
                        args = event.get("tool_args", {})
                        print(f"  [ACTING]  tool={tool}  args={json.dumps(args, ensure_ascii=False)}")
                        key_events.append({"phase": "acting", "tool": tool, "args": args})
                    elif phase == "observing":
                        summary = event.get("tool_result_summary", {})
                        print(f"  [OBSERVE] {json.dumps(summary, ensure_ascii=False)}")
                        key_events.append({"phase": "observing", "summary": summary})
                    elif phase in ("thinking", "planning", "step"):
                        msg = event.get("message") or event.get("content") or ""
                        if msg:
                            print(f"  [{phase.upper():<8}] {str(msg)[:120]}")
                    token = event.get("token")
                    if token:
                        answer_parts.append(str(token))
                    done = event.get("done")
                    if done:
                        sources = event.get("sources", [])
                        outcome = event.get("outcome")
                        print(f"  [DONE]    outcome={outcome}  sources={len(sources)}")
                        if sources:
                            for s in sources[:3]:
                                print(f"    • {s.get('document_name')} | score={s.get('score','?'):.3f} | heading={s.get('heading_path')}")

    answer = "".join(answer_parts)
    _sep("-")
    print(f"  ANSWER: {answer[:500]}")
    _sep()
    return key_events


async def main():
    print(f"conversation_id = {CONVERSATION_ID}")
    print(f"(Tìm trace_session='debug-muc-i' trên Langfuse để xem toàn bộ trace)\n")

    timeout = httpx.Timeout(120, connect=10)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            token, user_id = await login(client)
            print(f"Logged in as user_id={user_id}\n")
        except Exception as exc:
            print(f"Login failed: {exc}")
            sys.exit(1)

        for i, q in enumerate(QUESTIONS, 1):
            await ask(client, token, user_id, q, i)
            await asyncio.sleep(2)  # nhỏ để tránh rate limit


if __name__ == "__main__":
    asyncio.run(main())
