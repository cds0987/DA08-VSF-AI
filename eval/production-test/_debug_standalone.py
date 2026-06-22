#!/usr/bin/env python3
"""Test Q3/Q4 in ISOLATION (no prior context) to see if failure is context-dependent."""
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

STANDALONE_QUESTIONS = [
    "Cho tôi thêm thông tin về mục I",
    "tôi thấy trong tài liệu có mục 1 mà không lấy được thông tin à",
]


def _sep(char="─", width=80):
    print(char * width)


async def login(client: httpx.AsyncClient) -> tuple[str, str]:
    resp = await client.post(f"{USER_SERVICE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    resp.raise_for_status()
    data = resp.json()
    access_token = data["access_token"]
    me = await client.get(f"{USER_SERVICE}/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    me.raise_for_status()
    return access_token, me.json()["id"]


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


async def ask_standalone(client: httpx.AsyncClient, token: str, user_id: str, question: str, label: str):
    conv_id = str(uuid.uuid4())
    _sep("═")
    print(f"[{label}] STANDALONE (no context)")
    print(f"Q: {question}")
    print(f"conversation_id = {conv_id}")
    _sep()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    body = {
        "question": question,
        "user_id": user_id,
        "conversation_id": conv_id,
        "trace_session": "debug-standalone",
    }

    answer_parts: list[str] = []
    async with client.stream("POST", f"{QUERY_SERVICE}/query", headers=headers, json=body,
                              timeout=httpx.Timeout(60, connect=10)) as resp:
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code}: {(await resp.aread()).decode()[:300]}")
            return

        buffer = ""
        async for chunk in resp.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                packet, buffer = buffer.split("\n\n", 1)
                for event in parse_sse(packet + "\n\n"):
                    phase = event.get("phase")
                    if phase == "acting":
                        print(f"  [ACTING]  tool={event.get('tool')}  args={json.dumps(event.get('tool_args', {}), ensure_ascii=False)}")
                    elif phase == "observing":
                        print(f"  [OBSERVE] {json.dumps(event.get('tool_result_summary', {}), ensure_ascii=False)}")
                    elif phase in ("thinking", "planning"):
                        msg = event.get("message") or ""
                        if msg:
                            print(f"  [{phase.upper():<8}] {str(msg)[:120]}")
                    token_val = event.get("token")
                    if token_val:
                        answer_parts.append(str(token_val))
                    if event.get("done"):
                        outcome = event.get("outcome")
                        sources = event.get("sources", [])
                        print(f"  [DONE]    outcome={outcome}  sources={len(sources)}")
                        for s in sources[:3]:
                            print(f"    • {s.get('document_name')} | score={s.get('score','?'):.3f} | heading={s.get('heading_path')}")

    _sep("-")
    print(f"  ANSWER: {''.join(answer_parts)[:500]}")
    _sep()


async def main():
    timeout = httpx.Timeout(120, connect=10)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        token, user_id = await login(client)
        print(f"Logged in: user_id={user_id}\n")

        for i, q in enumerate(STANDALONE_QUESTIONS, 3):
            await ask_standalone(client, token, user_id, q, f"Q{i}-standalone")
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
