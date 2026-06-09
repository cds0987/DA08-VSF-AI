#!/usr/bin/env python3
"""
E2E integration test: hr-service + mcp-service proxy (real Docker).

Phase 1 — hr-service standalone (Docker + real Postgres):
  Gọi trực tiếp http://localhost:8004 để kiểm tra hr → Postgres path.

Phase 2 — mcp-service → hr-service proxy (Docker → Docker):
  Gọi MCP Streamable HTTP endpoint http://localhost:8003/mcp để kiểm tra
  toàn bộ chain mcp → hr → Postgres không bị break bởi bất kỳ mock nào.

Seed UUIDs khớp với migration 0001_create_hr_schema.py.
"""
from __future__ import annotations

import json
import os
import sys

import httpx

HR_URL = os.getenv("HR_URL", "http://localhost:8004")
MCP_URL = os.getenv("MCP_URL", "http://localhost:8003/mcp")
HR_TOKEN = os.getenv("HR_INTERNAL_TOKEN", "ci-secret")
MCP_TOKEN = os.getenv("MCP_INTERNAL_TOKEN", "ci-mcp-token")

# Seed UUIDs từ migration 0001_create_hr_schema.py
USER_HR = "11111111-1111-4111-8111-111111111111"
USER_FINANCE = "22222222-2222-4222-8222-222222222222"
USER_UNKNOWN = "00000000-0000-0000-0000-000000000000"

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"

_results: list[bool] = []
_failures: list[str] = []


def chk(label: str, cond: bool, note: str = "") -> bool:
    mark = PASS if cond else FAIL
    line = f"  {mark}  {label}"
    if note:
        line += f"\n         {note}"
    print(line)
    _results.append(cond)
    if not cond:
        _failures.append(label)
    return cond


# ── Minimal MCP Streamable HTTP client ───────────────────────────────────────

def _parse_sse_result(text: str) -> dict | None:
    """Trích kết quả từ SSE body: tìm dòng 'data: {...}' có key 'result'."""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        chunk = line[6:].strip()
        if not chunk:
            continue
        try:
            parsed = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if "result" not in parsed:
            continue
        content = parsed["result"].get("content", [])
        if not content:
            return parsed["result"]
        first = content[0]
        if first.get("type") == "text":
            try:
                return json.loads(first["text"])
            except json.JSONDecodeError:
                return {"raw": first["text"]}
        return first
    return None


def mcp_init(timeout: float = 15.0) -> str:
    """Khởi tạo MCP session, trả về session_id (chuỗi rỗng nếu server không trả)."""
    payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ci-e2e", "version": "1"},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Internal-Token": MCP_TOKEN,
    }
    with httpx.Client(timeout=timeout) as client:
        with client.stream("POST", MCP_URL, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            session_id = resp.headers.get("mcp-session-id", "")
            resp.read()
    return session_id


def mcp_call_tool(
    name: str,
    arguments: dict,
    session_id: str = "",
    timeout: float = 15.0,
) -> dict | None:
    """Gọi MCP tool qua Streamable HTTP, trả về dict kết quả từ tool."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Internal-Token": MCP_TOKEN,
    }
    if session_id:
        headers["mcp-session-id"] = session_id

    with httpx.Client(timeout=timeout) as client:
        with client.stream("POST", MCP_URL, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            body = resp.read().decode("utf-8")

    if "text/event-stream" in ct:
        return _parse_sse_result(body)

    # Plain JSON response
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    if "result" in data:
        content = data["result"].get("content", [])
        if content and content[0].get("type") == "text":
            try:
                return json.loads(content[0]["text"])
            except json.JSONDecodeError:
                pass
        return data.get("result")
    return None


# ── Phase 1: hr-service standalone ───────────────────────────────────────────

def phase1_hr_direct() -> None:
    print("\n━━━ Phase 1: hr-service standalone (Docker → real Postgres) ━━━")
    client = httpx.Client(timeout=10.0, headers={"X-Internal-Token": HR_TOKEN})

    # 1.1 GET /health
    r = client.get(f"{HR_URL}/health")
    chk("GET /health → 200", r.status_code == 200)
    chk('health body == {"status":"ok"}', r.json() == {"status": "ok"}, str(r.text))

    # 1.2 leave_balance — real data từ seed migration
    r = client.post(f"{HR_URL}/hr/query",
                    json={"user_id": USER_HR, "intent": "leave_balance"})
    chk("leave_balance USER_HR → 200", r.status_code == 200)
    body = r.json()
    chk("contract shape {intent,data,summary}", set(body.keys()) == {"intent", "data", "summary"},
        str(body))
    data = body.get("data", {})
    chk("annual_remaining == annual_total - annual_used (real Postgres calc)",
        data.get("annual_remaining") == data.get("annual_total", -1) - data.get("annual_used", -1),
        f"remaining={data.get('annual_remaining')} total={data.get('annual_total')} used={data.get('annual_used')}")
    chk("summary has Vietnamese diacritics", "Bạn" in body.get("summary", ""),
        f"summary={body.get('summary','')!r}")

    # 1.3 Cross-user isolation — hai user phải thấy data khác nhau
    r2 = client.post(f"{HR_URL}/hr/query",
                     json={"user_id": USER_FINANCE, "intent": "leave_balance"})
    chk("leave_balance USER_FINANCE → 200", r2.status_code == 200)
    data2 = r2.json().get("data", {})
    chk("USER_HR vs USER_FINANCE data khác nhau (isolation)",
        data.get("annual_used") != data2.get("annual_used"),
        f"HR used={data.get('annual_used')} FINANCE used={data2.get('annual_used')}")

    # 1.4 leave_requests shape
    r = client.post(f"{HR_URL}/hr/query",
                    json={"user_id": USER_HR, "intent": "leave_requests"})
    chk("leave_requests → 200", r.status_code == 200)
    body = r.json()
    chk("leave_requests has requests list", isinstance(body.get("data", {}).get("requests"), list))

    # 1.5 attendance + onboarding
    for intent in ("attendance", "onboarding"):
        r = client.post(f"{HR_URL}/hr/query",
                        json={"user_id": USER_HR, "intent": intent})
        chk(f"{intent} → 200", r.status_code == 200)
        chk(f"{intent} shape ok", set(r.json().keys()) == {"intent", "data", "summary"})

    # 1.6 Auth — wrong token → 401
    r_bad = httpx.post(f"{HR_URL}/hr/query",
                       json={"user_id": USER_HR, "intent": "leave_balance"},
                       headers={"X-Internal-Token": "wrong-token"},
                       timeout=10)
    chk("wrong token → 401", r_bad.status_code == 401, str(r_bad.text))

    # 1.7 Auth — missing token → 401
    r_no = httpx.post(f"{HR_URL}/hr/query",
                      json={"user_id": USER_HR, "intent": "leave_balance"},
                      timeout=10)
    chk("no token → 401", r_no.status_code == 401, str(r_no.text))

    # 1.8 Unknown user → 404
    r_unk = client.post(f"{HR_URL}/hr/query",
                        json={"user_id": USER_UNKNOWN, "intent": "leave_balance"})
    chk("unknown user → 404", r_unk.status_code == 404, str(r_unk.text))

    # 1.9 Invalid intent (payroll not in MVP Literal) → 422
    r_inv = client.post(f"{HR_URL}/hr/query",
                        json={"user_id": USER_HR, "intent": "payroll"})
    chk("intent=payroll → 422", r_inv.status_code == 422)

    client.close()


# ── Phase 2: mcp-service → hr-service proxy ──────────────────────────────────

def phase2_mcp_proxy() -> None:
    print("\n━━━ Phase 2: mcp-service → hr-service proxy (Docker → Docker → Postgres) ━━━")

    # 2.1 Khởi tạo MCP session
    try:
        session_id = mcp_init()
        chk("MCP session init ok", True, f"session_id={session_id!r}")
    except Exception as exc:
        chk("MCP session init ok", False, str(exc))
        print(f"  {WARN}  Phase 2 bị skip do không khởi tạo được MCP session")
        return

    # 2.2 Tool call: leave_balance qua MCP → hr-service → Postgres
    try:
        result = mcp_call_tool("hr_query",
                               {"user_id": USER_HR, "intent": "leave_balance"},
                               session_id=session_id)
        chk("mcp tools/call hr_query → result not None", result is not None, str(result))
        if result:
            chk("mcp result contract {intent,data,summary}",
                set(result.keys()) >= {"intent", "data", "summary"},
                str(result))
            chk("mcp intent == leave_balance", result.get("intent") == "leave_balance")
            annual_rem = result.get("data", {}).get("annual_remaining")
            chk("mcp annual_remaining is int", isinstance(annual_rem, int),
                f"annual_remaining={annual_rem}")
    except Exception as exc:
        chk("mcp tools/call hr_query ok", False, str(exc))
        return

    # 2.3 Cross-user isolation qua MCP
    try:
        res_fin = mcp_call_tool("hr_query",
                                {"user_id": USER_FINANCE, "intent": "leave_balance"},
                                session_id=session_id)
        if result and res_fin:
            hr_used = result.get("data", {}).get("annual_used")
            fin_used = res_fin.get("data", {}).get("annual_used")
            chk("mcp cross-user isolation: data khác nhau", hr_used != fin_used,
                f"HR used={hr_used} FINANCE used={fin_used}")
    except Exception as exc:
        chk("mcp cross-user isolation ok", False, str(exc))

    # 2.4 Unknown user qua MCP → 404 từ hr-service → mcp bubble up 5xx
    try:
        res_unk = mcp_call_tool("hr_query",
                                {"user_id": USER_UNKNOWN, "intent": "leave_balance"},
                                session_id=session_id)
        # mcp-service nhận 404 từ hr-service → raise_for_status → MCP returns error
        chk("mcp unknown user → error propagated (no silent 200)",
            res_unk is None or "error" in str(res_unk).lower() or
            res_unk.get("intent") is None,
            str(res_unk))
    except httpx.HTTPStatusError as exc:
        chk("mcp unknown user → HTTP error propagated", True, str(exc))
    except Exception as exc:
        # MCP error response is also acceptable
        chk("mcp unknown user → error propagated (no silent 200)", True, str(exc))

    # 2.5 attendance qua MCP (test thêm intent)
    try:
        res_att = mcp_call_tool("hr_query",
                                {"user_id": USER_HR, "intent": "attendance"},
                                session_id=session_id)
        chk("mcp attendance ok", res_att is not None and res_att.get("intent") == "attendance",
            str(res_att))
    except Exception as exc:
        chk("mcp attendance ok", False, str(exc))


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"HR_URL  = {HR_URL}")
    print(f"MCP_URL = {MCP_URL}")

    phase1_hr_direct()
    phase2_mcp_proxy()

    total = len(_results)
    passed = sum(_results)
    print(f"\n{'═'*50}")
    print(f"Kết quả: {passed}/{total} checks pass")
    if _failures:
        print(f"\nFAIL ({len(_failures)}):")
        for f in _failures:
            print(f"  ✗ {f}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
