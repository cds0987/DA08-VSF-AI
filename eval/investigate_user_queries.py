# -*- coding: utf-8 -*-
"""
Điều tra tại sao các câu hỏi về "thông tin user / tài khoản" không trả về thông tin
gì cho frontend.

Câu hỏi test:
  Q1: "Tôi muốn tất cả các thông tin của user"
  Q2: "Tôi muốn thông tin tất cả tài khoản"
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import httpx


def _load_env() -> None:
    env_file = Path(__file__).parent / "production-test" / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env()

_base = os.environ.get("PROD_BASE_URL", "https://vsfchat.cloud").rstrip("/")
_parsed = _base.split("://", 1)
_origin = f"{_parsed[0]}://{_parsed[1].split('/')[0]}" if len(_parsed) > 1 else _base

BASE_URL   = _origin
USER_URL   = BASE_URL + os.environ.get("USER_SERVICE_PATH", "/api/user")
QUERY_URL  = BASE_URL + os.environ.get("QUERY_SERVICE_PATH", "/api/query")
LANGFUSE   = "https://langfuse.vsfchat.cloud/project/rag-chatbot"

QUESTIONS = [
    "Tôi muốn tất cả các thông tin của user",
    "Tôi muốn thông tin tất cả tài khoản",
]

OUTCOME_MAP = {
    1: "REFUSE", 2: "CLARIFY", 3: "NO_INFO",
    4: "OFF_TOPIC", 5: "SUCCESS", 6: "ERROR",
}


def _parse_sse_events(raw: str) -> list[dict]:
    """Parse tất cả SSE data: fields từ raw text stream."""
    events = []
    for block in raw.split("\n\n"):
        lines = [l.strip() for l in block.splitlines() if l.strip().startswith("data:")]
        for line in lines:
            data_str = line[5:].strip()
            try:
                obj = json.loads(data_str)
                if isinstance(obj, dict):
                    events.append(obj)
            except Exception:
                pass
    return events


async def send_question(
    http: httpx.AsyncClient,
    hdrs: dict,
    user_id: str,
    question: str,
) -> tuple[list[dict], str | None]:
    """Gửi 1 câu hỏi, trả về (all_events, error_msg)."""
    body = {
        "question": question,
        "user_id": user_id,
        "conversation_title": question[:60],
    }

    raw_buf = ""
    try:
        async with http.stream(
            "POST",
            QUERY_URL + "/query",
            headers=hdrs,
            json=body,
            timeout=httpx.Timeout(90, connect=10),
        ) as resp:
            if resp.status_code != 200:
                body_bytes = await resp.aread()
                return [], f"HTTP {resp.status_code}: {body_bytes.decode('utf-8', errors='replace')[:300]}"
            async for chunk in resp.aiter_text():
                raw_buf += chunk
    except Exception as exc:
        return [], f"request error [{type(exc).__name__}]: {exc!r}"

    return _parse_sse_events(raw_buf), None


def _analyse(question: str, events: list[dict]) -> None:
    print(f"\n{'='*65}")
    print(f"QUESTION: {question}")
    print(f"{'='*65}")

    if not events:
        print("  !! NO EVENTS RECEIVED (stream empty)")
        return

    # Phân loại events
    token_events   = [e for e in events if "token" in e]
    phase_events   = [e for e in events if e.get("phase") and not e.get("done")]
    tool_events    = [e for e in phase_events if e.get("tool")]
    node_events    = [e for e in events if e.get("node")]
    error_events   = [e for e in events if "error" in e and not e.get("token")]
    done_event     = next((e for e in reversed(events) if e.get("done")), None)

    # Answer text
    answer = "".join(str(e.get("token", "")) for e in token_events)

    # Nodes visited
    nodes_visited = [e.get("node") for e in node_events if e.get("node")]

    # Tool calls
    tools_called = []
    for te in tool_events:
        if te.get("tool") and te.get("phase") == "acting":
            tools_called.append({
                "tool": te.get("tool"),
                "args": te.get("tool_args", {}),
            })

    # Tool results
    tool_results = [e for e in events if e.get("phase") == "observing" and e.get("tool")]

    print(f"\n  NODES VISITED : {nodes_visited}")

    print(f"\n  TOOLS CALLED  :")
    if tools_called:
        for tc in tools_called:
            print(f"    - {tc['tool']}  args={tc['args']}")
    else:
        print("    (none)")

    print(f"\n  TOOL RESULTS  :")
    if tool_results:
        for tr in tool_results:
            summary = tr.get("tool_result_summary") or tr.get("tool_result", "")
            print(f"    - {tr.get('tool')} → {str(summary)[:200]}")
    else:
        print("    (none)")

    print(f"\n  ANSWER ({len(answer)} chars):")
    if answer:
        print(f"    {answer[:500]}")
    else:
        print("    !! EMPTY — no token events received")

    if error_events:
        print(f"\n  !! ERRORS:")
        for ee in error_events:
            print(f"    {ee}")

    if done_event:
        outcome_val = done_event.get("outcome")
        outcome_str = OUTCOME_MAP.get(outcome_val, f"unknown({outcome_val})")
        print(f"\n  DONE EVENT:")
        print(f"    outcome    = {outcome_str} ({outcome_val})")
        print(f"    sources    = {len(done_event.get('sources') or [])} items")
        print(f"    iterations = {done_event.get('iterations', '?')}")
        print(f"    cached     = {done_event.get('cached', False)}")
        print(f"    error_key  = {done_event.get('error', '(none)')}")
        print(f"    guardrail  = {done_event.get('guardrail', '(not set)')}")
        print(f"    iterations_key_present = {'iterations' in done_event}")
        tid = done_event.get("trace_id", "")
        if tid:
            print(f"    trace_id   = {tid}")
            print(f"    Langfuse   = {LANGFUSE}")
        else:
            print("    trace_id   = (không có — triage shortcut path không emit trace_id?)")
    else:
        print("\n  !! NO DONE EVENT")

    # Summary verdict
    print(f"\n  >> VERDICT: ", end="")
    if not answer and not error_events and done_event:
        outcome_val = done_event.get("outcome")
        if outcome_val == 5:  # SUCCESS
            print("SUCCESS nhưng answer rỗng → LLM không generate text, hoặc bị strip hết")
        elif outcome_val == 4:  # OFF_TOPIC
            print("OFF_TOPIC shortcut — tokens đã stream nhưng có thể frontend không render?")
        elif outcome_val == 1:  # REFUSE
            print("REFUSE — token có thể không được stream")
        else:
            print(f"outcome={OUTCOME_MAP.get(outcome_val, outcome_val)} với answer rỗng")
    elif not answer and error_events:
        print("STREAM ERROR — exception trong pipeline")
    elif answer:
        print(f"Có answer ({len(answer)} chars). Frontend có hiển thị không?")
    else:
        print("Unknown — không đủ data")


async def main() -> None:
    if not os.environ.get("PROD_EMAIL") or not os.environ.get("PROD_PASSWORD"):
        print("ERROR: PROD_EMAIL / PROD_PASSWORD not set in eval/production-test/.env")
        return

    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as http:
        # Login
        r = await http.post(
            f"{USER_URL}/auth/login",
            json={"email": os.environ["PROD_EMAIL"], "password": os.environ["PROD_PASSWORD"]},
        )
        if r.status_code != 200:
            print(f"Login failed: {r.status_code} {r.text[:300]}")
            return
        token    = r.json()["access_token"]
        me_resp  = await http.get(f"{USER_URL}/auth/me", headers={"Authorization": f"Bearer {token}"})
        me       = me_resp.json()
        user_id  = me["id"]
        print(f"Logged in: {me['email']}  user_id={user_id}")
        print(f"Base: {BASE_URL}  |  Query: {QUERY_URL}")

        hdrs = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        for question in QUESTIONS:
            events, err = await send_question(http, hdrs, user_id, question)
            if err:
                print(f"\n!! REQUEST ERROR for {question!r}: {err}")
                continue
            _analyse(question, events)
            await asyncio.sleep(4)

    print("\n" + "="*65)
    print("Done. Tra cứu trace_id ở trên trong Langfuse để xem triage + LLM output.")
    print("="*65)


asyncio.run(main())
