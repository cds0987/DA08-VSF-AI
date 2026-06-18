# -*- coding: utf-8 -*-
"""
Test 3 câu hỏi liên tiếp trong cùng một conversation để kiểm tra:
  Q1: "Cho tôi thông tin về HR"
  Q2: "Chính sách & quy trình nội bộ"
  Q3: "10 file trên là file gì vậy"  ← diagnose tại sao không hỏi lại
"""
import asyncio
import json
import sys
import httpx

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import os
from pathlib import Path

def _load_env() -> None:
    env_file = Path(__file__).parent / "production-test" / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

_load_env()

_base = os.environ.get("PROD_BASE_URL", "https://vsfchat.cloud").rstrip("/")
_parsed = _base.split("://", 1)
_origin = f"{_parsed[0]}://{_parsed[1].split('/')[0]}" if len(_parsed) > 1 else _base

BASE_URL = _origin
USER_URL = BASE_URL + os.environ.get("USER_SERVICE_PATH", "/api/user")
QUERY_URL = BASE_URL + os.environ.get("QUERY_SERVICE_PATH", "/api/query")

_EMAIL = os.environ.get("PROD_EMAIL", "")
_PASSWORD = os.environ.get("PROD_PASSWORD", "")

QUESTIONS = [
    "Cho tôi thông tin về HR",
    "Chính sách & quy trình nội bộ",
    "10 file trên là file gì vậy",
]

OUTCOME_MAP = {1: "REFUSE", 2: "CLARIFY", 3: "NO_INFO", 4: "OFF_TOPIC", 5: "SUCCESS", 6: "ERROR"}


def parse_sse_block(block: str) -> list[dict]:
    events = []
    lines = [l.strip() for l in block.splitlines() if l.strip().startswith("data:")]
    if lines:
        data_str = "\n".join(l[5:].strip() for l in lines)
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

    buffer = ""
    raw_events = []

    async with http.stream(
        "POST", QUERY_URL + "/query",
        headers=hdrs, json=body,
        timeout=httpx.Timeout(60, connect=10)
    ) as resp:
        if resp.status_code != 200:
            body_text = (await resp.aread()).decode("utf-8", errors="replace")
            return None, [], f"HTTP {resp.status_code}: {body_text[:300]}"
        async for chunk in resp.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                pkt, buffer = buffer.split("\n\n", 1)
                for evt in parse_sse_block(pkt):
                    raw_events.append(evt)

    done_evt = next((e for e in reversed(raw_events) if e.get("done")), None)
    return done_evt, raw_events, None


async def main():
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as http:
        if not _EMAIL or not _PASSWORD:
            print("ERROR: PROD_EMAIL / PROD_PASSWORD not set. Copy eval/production-test/.env.example to .env and fill in credentials.")
            return
        # Login
        r = await http.post(
            f"{USER_URL}/auth/login",
            json={"email": _EMAIL, "password": _PASSWORD}
        )
        if r.status_code != 200:
            print(f"Login failed: {r.status_code} {r.text[:200]}")
            return
        token = r.json()["access_token"]
        me = await http.get(f"{USER_URL}/auth/me", headers={"Authorization": f"Bearer {token}"})
        user_id = me.json()["id"]
        print(f"Logged in: {me.json()['email']} | user_id={user_id}\n")

        hdrs = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        # conv_id sẽ được trích xuất sau Q1 (API không hỗ trợ POST create)
        conv_id = None
        print()

        print("=" * 70)
        print("TEST: 3 câu hỏi liên tiếp — chẩn đoán META/sources behavior")
        print(f"conv_id = {conv_id}")
        print("=" * 70)

        for i, question in enumerate(QUESTIONS, 1):
            print(f"\n{'='*55}")
            print(f"Q{i}: {question}")

            done, events, err = await send_question(http, hdrs, user_id, question, conversation_id=conv_id)
            if err:
                print(f"  ERROR: {err}")
                continue

            tokens = [str(e.get("token", "")) for e in events if "token" in e]
            answer = "".join(tokens)
            phase_evts = [e for e in events if e.get("phase") and not e.get("done")]
            tool_evts = [e for e in phase_evts if e.get("tool")]
            node_evts = [e for e in events if e.get("node")]

            print(f"\n  ANSWER ({len(answer)} chars):")
            print(f"  {answer}")

            if done:
                outcome = done.get("outcome")
                sources = done.get("sources") or []
                session_id = done.get("session_id", "")
                trace_id = done.get("trace_id", "")
                print(f"\n  outcome = {OUTCOME_MAP.get(outcome, outcome)} ({outcome})")
                print(f"  sources count = {len(sources)}")
                print(f"  cached = {done.get('cached', False)}")
                if sources:
                    print("  Sources trả về frontend:")
                    for s in sources:
                        score = s.get("score")
                        score_str = f"{score:.3f}" if isinstance(score, (int, float)) else str(score)
                        print(f"    - {s.get('document_name', '?')!r}  score={score_str}  page={s.get('page_number', '?')}")
                else:
                    print("  Sources: NONE")
                if session_id:
                    print(f"  session_id = {session_id}")
                if trace_id:
                    print(f"  trace_id  = {trace_id}")
                    print(f"  Langfuse  = https://langfuse.vsfchat.cloud/project/rag-chatbot (filter by trace_id)")
            else:
                print("  NO DONE EVENT")

            nodes_seen = [e.get("node") for e in node_evts if e.get("node")]
            print(f"  nodes: {nodes_seen}")
            if tool_evts:
                for te in tool_evts:
                    print(f"  tool: {te.get('tool')}  args={te.get('tool_args')}")

            # Sau Q1: trích conv_id từ conversations list
            if i == 1 and not conv_id:
                await asyncio.sleep(1)
                try:
                    r_convs = await http.get(
                        f"{QUERY_URL}/conversations",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"limit": 3},
                        timeout=10,
                    )
                    if r_convs.status_code == 200:
                        data = r_convs.json()
                        items = data if isinstance(data, list) else data.get("items", data.get("conversations", []))
                        if items and isinstance(items, list):
                            cid = items[0].get("id") or items[0].get("conversation_id")
                            if cid:
                                conv_id = str(cid)
                                print(f"  => conv_id extracted: {conv_id}")
                except Exception as e:
                    print(f"  => conv_id extraction failed: {e}")
                if not conv_id:
                    print("  => WARNING: không lấy được conv_id, Q2/Q3 sẽ không có context")

            await asyncio.sleep(3)  # tránh rate limit

        print("\n" + "=" * 70)
        print("Done. Kiểm tra trace_id ở trên trong Langfuse để xem triage decision.")
        print("=" * 70)


asyncio.run(main())
