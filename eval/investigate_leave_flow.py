# -*- coding: utf-8 -*-
"""
Điều tra luồng hội thoại xin nghỉ phép (multi-turn).

Chuỗi câu hỏi (cùng 1 conversation):
  Q1: "tôi muốn xin nghỉ"
  Q2: "nghỉ 20/4"
  Q3: "cùng ngày năm sau"
  Q4: "nghỉ ốm do gãy chân"

Mục đích:
  - Kiểm tra triage route từng turn (ALLOW/CLARIFY/SAFETY?)
  - Kiểm tra context lịch sử hội thoại có được truyền sang turn tiếp không
  - Xem lý do hệ thống không đặt lịch được
"""
import asyncio
import json
import os
import sys
import uuid
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

BASE_URL  = _origin
USER_URL  = BASE_URL + os.environ.get("USER_SERVICE_PATH", "/api/user")
QUERY_URL = BASE_URL + os.environ.get("QUERY_SERVICE_PATH", "/api/query")
LANGFUSE  = "https://langfuse.vsfchat.cloud/project/rag-chatbot"

# 4 câu hỏi cần test (theo thứ tự, cùng 1 conversation)
QUESTIONS = [
    "tôi muốn xin nghỉ",
    "nghỉ 20/4",
    "cùng ngày năm sau",
    "nghỉ ốm do gãy chân",
]

OUTCOME_MAP = {
    1: "REFUSE", 2: "CLARIFY", 3: "NO_INFO",
    4: "OFF_TOPIC", 5: "SUCCESS", 6: "ERROR",
}


def _parse_sse_events(raw: str) -> list[dict]:
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
    conversation_title: str,
    conversation_id: str | None,
) -> tuple[list[dict], str | None]:
    body: dict = {
        "question": question,
        "user_id": user_id,
        "conversation_title": conversation_title,
    }
    if conversation_id:
        body["conversation_id"] = conversation_id

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


def _analyse(turn: int, question: str, events: list[dict], conversation_id: str | None) -> str | None:
    """Print phân tích chi tiết, trả về conversation_id từ done event (nếu có)."""
    print(f"\n{'='*70}")
    print(f"TURN {turn}: {question!r}")
    print(f"  conversation_id truyền vào: {conversation_id or '(None — dùng latest)'}")
    print(f"{'='*70}")

    if not events:
        print("  !! NO EVENTS RECEIVED (stream empty)")
        return None

    token_events  = [e for e in events if "token" in e]
    phase_events  = [e for e in events if e.get("phase") and not e.get("done")]
    tool_events   = [e for e in phase_events if e.get("tool") and e.get("phase") == "acting"]
    error_events  = [e for e in events if "error" in e and not e.get("token")]
    done_event    = next((e for e in reversed(events) if e.get("done")), None)

    answer = "".join(str(e.get("token", "")) for e in token_events)

    # Triage route (nếu có trong phase events)
    triage_events = [e for e in events if e.get("node") == "triage_node" or e.get("phase") == "triage"]
    triage_route  = None
    for e in events:
        if e.get("triage_route") or e.get("route"):
            triage_route = e.get("triage_route") or e.get("route")

    # Tools gọi
    tools_called = []
    for te in tool_events:
        tools_called.append({"tool": te.get("tool"), "args": te.get("tool_args", {})})

    # Phase events (thinking/acting/observing)
    phases_seen = []
    for e in phase_events:
        p = e.get("phase")
        if p and p not in phases_seen:
            phases_seen.append(p)

    # Nodes visited
    node_events  = [e for e in events if e.get("node")]
    nodes_visited = []
    for e in node_events:
        n = e.get("node")
        if n and n not in nodes_visited:
            nodes_visited.append(n)

    print(f"\n  NODES VISITED  : {nodes_visited}")
    print(f"  PHASES SEEN    : {phases_seen}")
    if triage_route:
        print(f"  TRIAGE ROUTE   : {triage_route}")

    print(f"\n  TOOLS CALLED   :")
    if tools_called:
        for tc in tools_called:
            print(f"    - {tc['tool']}  args={tc['args']}")
    else:
        print("    (none)")

    # Tool results summary
    observe_events = [e for e in events if e.get("phase") == "observing" and e.get("tool")]
    if observe_events:
        print(f"\n  TOOL RESULTS   :")
        for tr in observe_events:
            summary = tr.get("tool_result_summary") or str(tr.get("tool_result", ""))[:200]
            print(f"    - {tr.get('tool')} → {summary[:250]}")

    print(f"\n  ANSWER ({len(answer)} chars):")
    if answer:
        # Hiển thị đầy đủ để thấy rõ JSON action hay text
        print(f"    {answer[:800]}")
    else:
        print("    !! EMPTY — no token events")

    if error_events:
        print(f"\n  !! ERRORS:")
        for ee in error_events:
            print(f"    {ee}")

    returned_conv_id = None
    if done_event:
        outcome_val = done_event.get("outcome")
        outcome_str = OUTCOME_MAP.get(outcome_val, f"unknown({outcome_val})")
        returned_conv_id = done_event.get("conversation_id")
        print(f"\n  DONE EVENT:")
        print(f"    outcome          = {outcome_str} ({outcome_val})")
        print(f"    guardrail        = {done_event.get('guardrail', '(not set)')}")
        print(f"    iterations       = {done_event.get('iterations', '?')}")
        print(f"    sources          = {len(done_event.get('sources') or [])} items")
        print(f"    conversation_id  = {returned_conv_id or '(not in event)'}")
        tid = done_event.get("trace_id", "")
        if tid:
            print(f"    trace_id         = {tid}")
            print(f"    Langfuse trace   = {LANGFUSE}/traces/{tid}")
        else:
            print("    trace_id         = (không có — triage shortcut không emit trace_id)")

        # Kiểm tra nếu answer là JSON action (create_leave_request)
        stripped = answer.strip()
        if stripped.startswith("{") and "action_type" in stripped:
            try:
                action = json.loads(stripped)
                print(f"\n  >> ACTION CARD DETECTED: {action.get('action_type')}")
                for item in action.get("items", []):
                    print(f"     item: {item}")
            except Exception:
                print(f"\n  >> Có vẻ là action JSON nhưng parse thất bại")
    else:
        print("\n  !! NO DONE EVENT")

    # Verdict
    print(f"\n  >> VERDICT: ", end="")
    if not answer and done_event:
        outcome_val = done_event.get("outcome")
        if outcome_val == 4:
            print("OFF_TOPIC/SAFETY shortcut — câu này bị từ chối hoặc safety canned answer")
        elif outcome_val == 2:
            print("CLARIFY — bot hỏi ngược lại người dùng để làm rõ")
        elif outcome_val == 1:
            print("REFUSE — ngoài phạm vi")
        else:
            print(f"outcome={OUTCOME_MAP.get(outcome_val, outcome_val)} nhưng answer rỗng")
    elif not answer and error_events:
        print("STREAM ERROR — exception trong pipeline")
    elif answer:
        stripped = answer.strip()
        if stripped.startswith("{") and "action_type" in stripped:
            print(f"ACTION CARD — hệ thống đã chuẩn bị draft ({len(answer)} chars)")
        else:
            print(f"Text answer ({len(answer)} chars)")
    else:
        print("Unknown — không đủ data")

    return returned_conv_id


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
        token   = r.json()["access_token"]
        me_resp = await http.get(f"{USER_URL}/auth/me", headers={"Authorization": f"Bearer {token}"})
        me      = me_resp.json()
        user_id = me["id"]
        print(f"Logged in : {me['email']}  user_id={user_id}")
        print(f"Base URL  : {BASE_URL}")
        print(f"Query URL : {QUERY_URL}")

        hdrs = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        # Dùng 1 conversation_title cố định để tất cả turns vào cùng 1 conversation
        conv_title = f"[TEST] xin-nghi-flow-{uuid.uuid4().hex[:6]}"
        conv_id: str | None = None  # sẽ lấy từ done event nếu server trả về

        print(f"\nConversation title: {conv_title!r}")
        print("Sẽ gửi 4 câu lần lượt, cách nhau 4 giây...\n")

        for i, question in enumerate(QUESTIONS, start=1):
            events, err = await send_question(
                http, hdrs, user_id, question,
                conversation_title=conv_title,
                conversation_id=conv_id,
            )
            if err:
                print(f"\n!! REQUEST ERROR for Q{i} {question!r}: {err}")
                await asyncio.sleep(4)
                continue

            returned_id = _analyse(i, question, events, conv_id)
            # Nếu server trả về conversation_id trong done event, dùng cho turn tiếp
            if returned_id and conv_id is None:
                conv_id = returned_id
                print(f"\n  [Lưu conversation_id={conv_id} cho các turn tiếp theo]")

            if i < len(QUESTIONS):
                print(f"\n  [Chờ 4 giây trước turn {i+1}...]")
                await asyncio.sleep(4)

    print(f"\n{'='*70}")
    print("DONE. Tìm trace_id ở trên và tra cứu tại Langfuse:")
    print(f"  {LANGFUSE}")
    print(f"{'='*70}")


asyncio.run(main())
