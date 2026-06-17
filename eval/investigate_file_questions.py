# -*- coding: utf-8 -*-
"""
Test 4 follow-up questions including colloquial "file" references.

Q1: "biết gì về HR"
Q2: "chính sách nghỉ phép"
Q3: "5 file này là gì vậy"   ← should META (sources), not RAG
Q4: "5 file ở trên đó"       ← should META (sources), not RAG
"""
import asyncio
import json
import sys
import httpx

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

BASE_URL = "https://vsfchat.cloud"
USER_URL = BASE_URL + "/api/user"
QUERY_URL = BASE_URL + "/api/query"

QUESTIONS = [
    "biết gì về HR",
    "chính sách nghỉ phép",
    "5 file này là gì vậy",
    "5 file ở trên đó",
]

OUTCOME_MAP = {1: "REFUSE", 2: "CLARIFY", 3: "NO_INFO", 4: "OFF_TOPIC", 5: "SUCCESS", 6: "ERROR"}


def parse_sse_events(raw_text: str) -> list[dict]:
    events = []
    for block in raw_text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        lines = [l for l in block.splitlines() if l.strip().startswith("data:")]
        if not lines:
            continue
        data_str = lines[0][5:].strip()
        try:
            parsed = json.loads(data_str)
            if isinstance(parsed, dict):
                events.append(parsed)
        except Exception:
            pass
    return events


async def send_question(http, hdrs, user_id, question, conversation_id=None):
    body = {
        "question": question,
        "user_id": user_id,
        "conversation_title": question[:50],
    }
    if conversation_id:
        body["conversation_id"] = str(conversation_id)

    full_text = ""
    async with http.stream(
        "POST", QUERY_URL + "/query",
        headers=hdrs, json=body,
        timeout=httpx.Timeout(90, connect=10),
    ) as resp:
        if resp.status_code != 200:
            body_bytes = await resp.aread()
            return None, [], f"HTTP {resp.status_code}: {body_bytes.decode('utf-8', errors='replace')[:300]}"
        async for chunk in resp.aiter_text():
            full_text += chunk

    raw_events = parse_sse_events(full_text)
    done_evt = next((e for e in reversed(raw_events) if e.get("done")), None)
    return done_evt, raw_events, None


async def get_conv_id(http, hdrs):
    await asyncio.sleep(1)
    try:
        r = await http.get(
            f"{QUERY_URL}/conversations",
            headers={"Authorization": hdrs["Authorization"]},
            params={"limit": 3},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else data.get("conversations", data.get("items", []))
            if items and isinstance(items, list):
                cid = items[0].get("id") or items[0].get("conversation_id")
                if cid:
                    return str(cid)
    except Exception as e:
        print(f"  [conv list] error: {e}")
    return None


async def main():
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
        r = await http.post(
            f"{USER_URL}/auth/login",
            json={"email": "admin@company.com", "password": "DemoAdminPassword123!"}
        )
        token = r.json()["access_token"]
        me = await http.get(f"{USER_URL}/auth/me", headers={"Authorization": f"Bearer {token}"})
        user_id = me.json()["id"]
        print(f"Logged in: {me.json()['email']} | user_id={user_id}\n")

        hdrs = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        print("=" * 70)
        print("Test: 'file' follow-up questions (same conversation)")
        print("Expected: Q3/Q4 → META(sources), no RAG, list files from Q2")
        print("=" * 70)

        conv_id = None

        for i, question in enumerate(QUESTIONS, 1):
            print(f"\n{'='*60}")
            print(f"Q{i}: {question}")
            print(f"  conv_id: {conv_id}")

            done, events, err = await send_question(http, hdrs, user_id, question, conv_id)
            if err:
                print(f"  ERROR: {err}")
                continue

            tokens = [str(e.get("token", "")) for e in events if "token" in e]
            answer = "".join(tokens)
            node_evts = [e for e in events if e.get("node")]
            phase_evts = [e for e in events if e.get("phase") and not e.get("done")]
            tool_evts = [e for e in phase_evts if e.get("tool")]

            print(f"  Answer ({len(answer)} chars):")
            if answer:
                print(f"    {answer[:500]}")
            else:
                print("    [EMPTY]")

            if done:
                outcome = done.get("outcome")
                sources = done.get("sources") or []
                print(f"  outcome={OUTCOME_MAP.get(outcome, outcome)} | sources={len(sources)} | cached={done.get('cached', False)}")
                if sources:
                    print("  Sources panel:")
                    for s in sources[:5]:
                        print(f"    - {s.get('document_name', '?')!r}  score={s.get('score', 0):.3f}")
                else:
                    print("  Sources panel: empty (expected for META)")
                if done.get("trace_id"):
                    print(f"  trace_id={done['trace_id']}")
            else:
                print("  NO DONE EVENT")

            nodes_seen = [e.get("node") for e in node_evts if e.get("node")]
            print(f"  nodes: {nodes_seen}")
            for te in tool_evts:
                print(f"  tool: {te.get('tool')}  args={te.get('tool_args')}")

            if i == 1 and not conv_id:
                conv_id = await get_conv_id(http, hdrs)
                if conv_id:
                    print(f"  => conv_id: {conv_id}")
                else:
                    print("  => WARNING: could not extract conv_id")

            await asyncio.sleep(3)

        print("\n" + "=" * 70)
        print("Done.")


asyncio.run(main())
