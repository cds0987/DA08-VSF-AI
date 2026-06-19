# -*- coding: utf-8 -*-
"""
Test 2 câu về CNHC Employee Handbook:
  Q1: "cho tôi thông tin CNHC Employee Handbook"
  Q2: "Các mục trong sổ tay gồm gì"

Phân tích: context Q1 có được mang sang Q2 không, triage route, sources.
"""
import asyncio, json, os, sys, uuid
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import httpx

def _load_env():
    env_file = Path(__file__).parent / "production-test" / ".env"
    if not env_file.exists(): return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ: os.environ[k] = v

_load_env()
_base   = os.environ.get("PROD_BASE_URL", "https://vsfchat.cloud").rstrip("/")
_parsed = _base.split("://", 1)
_origin = f"{_parsed[0]}://{_parsed[1].split('/')[0]}" if len(_parsed) > 1 else _base
BASE_URL  = _origin
USER_URL  = BASE_URL + os.environ.get("USER_SERVICE_PATH", "/api/user")
QUERY_URL = BASE_URL + os.environ.get("QUERY_SERVICE_PATH", "/api/query")
LANGFUSE  = "https://langfuse.vsfchat.cloud/project/rag-chatbot"

QUESTIONS = [
    "cho tôi thông tin CNHC Employee Handbook",
    "Các mục trong sổ tay gồm gì",
]

OUTCOME_MAP = {1:"REFUSE",2:"CLARIFY",3:"NO_INFO",4:"OFF_TOPIC",5:"SUCCESS",6:"ERROR"}

def _parse_sse(raw: str) -> list[dict]:
    events = []
    for block in raw.split("\n\n"):
        for line in block.splitlines():
            line = line.strip()
            if not line.startswith("data:"): continue
            try:
                obj = json.loads(line[5:].strip())
                if isinstance(obj, dict): events.append(obj)
            except Exception: pass
    return events

async def send(http, hdrs, user_id, question, conv_title, conv_id):
    body = {"question": question, "user_id": user_id, "conversation_title": conv_title}
    if conv_id: body["conversation_id"] = conv_id
    raw = ""
    try:
        async with http.stream("POST", QUERY_URL+"/query", headers=hdrs, json=body,
                               timeout=httpx.Timeout(90, connect=10)) as resp:
            if resp.status_code != 200:
                b = await resp.aread()
                return [], f"HTTP {resp.status_code}: {b.decode(errors='replace')[:200]}"
            async for chunk in resp.aiter_text(): raw += chunk
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc!r}"
    return _parse_sse(raw), None

def analyse(turn, question, events, conv_id_sent):
    print(f"\n{'='*72}")
    print(f"TURN {turn}: {question!r}")
    print(f"  conversation_id gửi: {conv_id_sent or '(None – dùng latest)'}")
    print(f"{'='*72}")
    if not events:
        print("  !! NO EVENTS"); return None

    token_events   = [e for e in events if "token" in e]
    acting_events  = [e for e in events if e.get("phase")=="acting"  and e.get("tool")]
    observe_events = [e for e in events if e.get("phase")=="observing" and e.get("tool")]
    done           = next((e for e in reversed(events) if e.get("done")), None)
    node_events    = [e for e in events if e.get("node")]

    answer = "".join(str(e.get("token","")) for e in token_events)

    nodes  = []
    for e in node_events:
        n = e.get("node")
        if n and n not in nodes: nodes.append(n)

    tools_called = [{"tool": e.get("tool"), "args": e.get("tool_args",{})}
                    for e in acting_events]

    print(f"\n  NODES VISITED : {nodes}")

    print(f"\n  TOOLS CALLED  :")
    if tools_called:
        for tc in tools_called:
            print(f"    - {tc['tool']}  args={tc['args']}")
    else:
        print("    (none)")

    print(f"\n  TOOL RESULTS  :")
    if observe_events:
        for tr in observe_events:
            summary = tr.get("tool_result_summary") or str(tr.get("tool_result",""))
            print(f"    - {tr.get('tool')} → {str(summary)[:300]}")
    else:
        print("    (none)")

    print(f"\n  ANSWER ({len(answer)} chars):")
    print(f"    {answer[:1000]}")

    conv_id_returned = None
    if done:
        outcome_val = done.get("outcome")
        conv_id_returned = done.get("conversation_id")
        sources = done.get("sources") or []
        tid = done.get("trace_id","")
        print(f"\n  DONE EVENT:")
        print(f"    outcome         = {OUTCOME_MAP.get(outcome_val,outcome_val)} ({outcome_val})")
        print(f"    sources count   = {len(sources)}")
        if sources:
            for s in sources[:5]:
                print(f"      · {s.get('document_name','?')} — chunk_id={s.get('chunk_id','?')}")
        print(f"    iterations      = {done.get('iterations','?')}")
        print(f"    conversation_id = {conv_id_returned or '(không có trong event)'}")
        if tid:
            print(f"    trace_id        = {tid}")
            print(f"    Langfuse        = {LANGFUSE}/traces/{tid}")
        else:
            print("    trace_id        = (không có — shortcut path?)")
    else:
        print("\n  !! NO DONE EVENT")

    return conv_id_returned

async def main():
    if not os.environ.get("PROD_EMAIL") or not os.environ.get("PROD_PASSWORD"):
        print("ERROR: PROD_EMAIL / PROD_PASSWORD not set"); return

    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as http:
        r = await http.post(f"{USER_URL}/auth/login",
            json={"email": os.environ["PROD_EMAIL"], "password": os.environ["PROD_PASSWORD"]})
        if r.status_code != 200:
            print(f"Login failed: {r.status_code} {r.text[:200]}"); return
        token   = r.json()["access_token"]
        me      = (await http.get(f"{USER_URL}/auth/me",
                    headers={"Authorization": f"Bearer {token}"})).json()
        user_id = me["id"]
        print(f"Logged in : {me['email']}  user_id={user_id}")
        print(f"Query URL : {QUERY_URL}")

        hdrs = {"Authorization": f"Bearer {token}",
                "Content-Type": "application/json", "Accept": "text/event-stream"}

        conv_title = f"[TEST] handbook-{uuid.uuid4().hex[:6]}"
        conv_id: str | None = None
        print(f"\nConversation title: {conv_title!r}\n")

        for i, q in enumerate(QUESTIONS, 1):
            events, err = await send(http, hdrs, user_id, q, conv_title, conv_id)
            if err:
                print(f"\n!! REQUEST ERROR Q{i}: {err}")
            else:
                ret = analyse(i, q, events, conv_id)
                if ret and conv_id is None:
                    conv_id = ret
                    print(f"  [conversation_id={conv_id} dùng cho turn tiếp]")
            if i < len(QUESTIONS):
                print("\n  [Chờ 4 giây...]\n")
                await asyncio.sleep(4)

    print(f"\n{'='*72}")
    print(f"DONE. Langfuse: {LANGFUSE}")
    print(f"{'='*72}")

asyncio.run(main())
