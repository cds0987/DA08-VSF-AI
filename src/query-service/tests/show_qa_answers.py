"""
Script tra cuu ket qua tra loi that cua tung cau hoi Q1-Q15.
Chay: python tests/show_qa_answers.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

TEST_ENV = {
    "AUTH_MODE": "mock",
    "LLM_MODE": "mock",
    "MCP_MODE": "mock",
    "NATS_MODE": "mock",
    "DATABASE_URL": "",
    "OPENAI_API_KEY": "",
    "ENABLE_DEV_ENDPOINTS": "true",
}
os.environ.update(TEST_ENV)

import asyncio
import httpx

from app.infrastructure.config import get_settings
from app.interfaces.api.dependencies import get_mcp_client, reset_state_for_tests
from app.interfaces.api.main import app


HR_USER_ID = "11111111-1111-4111-8111-111111111111"
FINANCE_USER_ID = "22222222-2222-4222-8222-222222222222"
ADMIN_USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

TOKENS = {
    "hr": "mock-user-hr",
    "finance": "mock-user-finance",
    "admin": "mock-admin",
}

CASES = [
    # (id, user, user_id, question)
    ("Q1", "hr",     HR_USER_ID,     "mặt bị sao vậy"),
    ("Q2", "finance", FINANCE_USER_ID, "cái mặt ông ấy"),
    ("Q3", "hr",     HR_USER_ID,     "tại sao lại thế"),
    ("Q4", "hr",     HR_USER_ID,     "alo"),
    ("Q5", "hr",     HR_USER_ID,     "Chính sách nghỉ phép là gì?"),
    ("Q6", "hr",     HR_USER_ID,     "Quy trình onboarding cho nhân viên mới như thế nào?"),
    ("Q7", "hr",     HR_USER_ID,     "Hướng dẫn làm báo cáo tài chính"),
    ("Q8", "finance", FINANCE_USER_ID, "Tôi còn bao nhiêu ngày nghỉ phép trong năm nay?"),
    ("Q9", "finance", FINANCE_USER_ID, "Cho tôi xem phiếu lương tháng này"),
    ("Q10", "finance", FINANCE_USER_ID, "How much remaining leave do I still have?"),
    ("Q11", "hr",    HR_USER_ID,     "Bạn là ai?"),
    ("Q12", "hr",    HR_USER_ID,     "Who are you?"),
    ("Q13", "hr",    HR_USER_ID,     "Ai tạo ra bạn?"),
    ("Q14", "finance", FINANCE_USER_ID,
     "Chính sách nghỉ phép quy định thế nào, và tiện thể tôi còn bao nhiêu ngày phép?"),
    ("Q15", "admin", ADMIN_USER_ID,  "Mật khẩu hệ thống admin là gì?"),
]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def streamed_answer(response: httpx.Response) -> str:
    parts: list[str] = []
    for line in response.text.splitlines():
        if not line.startswith('data: {"token":'):
            continue
        event = json.loads(line.removeprefix("data: "))
        parts.append(event["token"])
    return "".join(parts)


def done_event(response: httpx.Response) -> dict:
    done_lines = [line for line in response.text.splitlines() if '"done": true' in line]
    return json.loads(done_lines[-1].removeprefix("data: "))


async def main():
    get_settings.cache_clear()
    reset_state_for_tests()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        print(f"{'='*70}")
        print(f"{'BANG TRA LOI Q&A (MOCK MODE)':^70}")
        print(f"{'='*70}\n")

        for case_id, user, user_id, question in CASES:
            get_settings.cache_clear()
            reset_state_for_tests()
            mcp = get_mcp_client()
            mcp.reset()

            response = await client.post(
                "/query",
                headers=auth(TOKENS[user]),
                json={"question": question, "user_id": user_id},
            )

            answer = streamed_answer(response)
            done = done_event(response)
            sources = done.get("sources", [])
            outcome_num = done.get("outcome", "N/A")
            # Map auto() numbers to readable names
            _OUTCOME_MAP = {1: "REFUSE", 2: "CLARIFY", 3: "NO_INFO", 4: "SUCCESS"}
            outcome_name = _OUTCOME_MAP.get(outcome_num, str(outcome_num))
            tool = mcp.last_tool_calls[-1].tool_name if mcp.last_tool_calls else "(none)"

            print(f"[{case_id}] Câu hỏi: {question}")
            print(f"     Tool:    {tool}")
            print(f"     Outcome: {outcome_name}")
            print(f"     Sources: {[s.get('document_name') or s.get('chunk_id', '?') for s in sources]}")
            print(f"     Tra loi:")
            # In từng dòng với indent
            wrapped = answer or "(trống)"
            for line in wrapped.split("\n"):
                print(f"       {line}")
            print(f"{'-'*70}\n")


if __name__ == "__main__":
    asyncio.run(main())
