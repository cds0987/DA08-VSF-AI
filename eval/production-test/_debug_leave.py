#!/usr/bin/env python3
"""
Test leave_action flow: "Tôi muốn nghỉ ngày 23/6 đến 27/6 do bị đau chân"
Capture SSE events để thấy date_spec LLM tạo ra và lý do hỏi lại.
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import uuid

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = "https://vsfchat.cloud"
EMAIL = "admin@company.com"
PASSWORD = "DemoAdminPassword123!"
USER_SERVICE = f"{BASE}/api/user"
QUERY_SERVICE = f"{BASE}/api/query"


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


async def ask_leave(
    client: httpx.AsyncClient,
    token: str,
    user_id: str,
    question: str,
    label: str,
):
    conv_id = str(uuid.uuid4())
    _sep("═")
    print(f"[{label}]")
    print(f"Q: {question}")
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
        "trace_session": "debug-leave",
    }

    answer_parts: list[str] = []

    try:
        async with client.stream(
            "POST", f"{QUERY_SERVICE}/query",
            headers=headers, json=body,
            timeout=httpx.Timeout(90, connect=10),
        ) as resp:
            if resp.status_code != 200:
                raw = (await resp.aread()).decode()
                print(f"  HTTP {resp.status_code}: {raw[:300]}")
                return

            buffer = ""
            try:
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        packet, buffer = buffer.split("\n\n", 1)
                        for ev in parse_sse(packet + "\n\n"):
                            ph = ev.get("phase")
                            if ph == "acting":
                                tool = ev.get("tool", "")
                                args = ev.get("tool_args", {})
                                print(f"  [ACTING] tool={tool}")
                                print(f"           args={json.dumps(args, ensure_ascii=False)}")
                            elif ph == "observing":
                                s = ev.get("tool_result_summary", {})
                                print(f"  [OBSERVE] {json.dumps(s, ensure_ascii=False)}")
                            elif ph in ("thinking", "planning"):
                                msg = ev.get("message") or ""
                                if msg:
                                    print(f"  [{ph.upper():<8}] {str(msg)[:120]}")
                            t = ev.get("token")
                            if t:
                                answer_parts.append(str(t))
                            if ev.get("done"):
                                outcome = ev.get("outcome")
                                sources = ev.get("sources", [])
                                print(f"  [DONE] outcome={outcome}  sources={len(sources)}")
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout) as e:
                print(f"  [STREAM CUT] {type(e).__name__}: {e}")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")

    _sep("-")
    answer = "".join(answer_parts)
    print(f"  ANSWER: {answer[:600]}")
    _sep()


async def main():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        token, user_id = await login(client)
        print(f"Logged in: user_id={user_id}\n")

        # Test 1: câu gốc của user
        await ask_leave(
            client, token, user_id,
            "Tôi muốn nghỉ ngày 23/6 đến 27/6 do bị đau chân",
            "TEST-1: câu gốc (DD/MM range)",
        )
        await asyncio.sleep(2)

        # Test 2: thêm năm xem có hoạt động không
        await ask_leave(
            client, token, user_id,
            "Tôi muốn nghỉ ngày 23/6/2026 đến 27/6/2026 do bị đau chân",
            "TEST-2: với năm đầy đủ (baseline)",
        )
        await asyncio.sleep(2)

        # Test 3: dạng khác — "từ 23 đến 27 tháng 6"
        await ask_leave(
            client, token, user_id,
            "Tôi muốn nghỉ từ ngày 23 đến 27 tháng 6 do bị đau chân",
            "TEST-3: dạng 'từ ngày X đến Y tháng Z'",
        )


if __name__ == "__main__":
    asyncio.run(main())
