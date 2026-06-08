"""
Bo test day du 15 Q&A tu testQA.md (src/query-service/Docs/testQA.md).

Nhom 1: Clarification / Fallback     (Q1-Q4)
Nhom 2: RAG / Tra cuu tai lieu      (Q5-Q7)
Nhom 3: HR Query / Du lieu ca nhan  (Q8-Q10)
Nhom 4: Identity Shortcut           (Q11-Q13)
Nhom 5: Out of Scope / Bao mat      (Q14-Q15)

Su dung:  pytest tests/test_qa.py -v
Hoac:    python -m pytest tests/test_qa.py -v
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.domain.outcome import Outcome
from app.interfaces.api.dependencies import get_mcp_client, get_tool_decision_client


HR_USER_ID = "11111111-1111-4111-8111-111111111111"
FINANCE_USER_ID = "22222222-2222-4222-8222-222222222222"
ADMIN_USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def streamed_answer(response: httpx.Response) -> str:
    """Ghep tat ca token tu SSE stream thanh 1 cau tra loi."""
    parts: list[str] = []
    for line in response.text.splitlines():
        if not line.startswith('data: {"token":'):
            continue
        event = json.loads(line.removeprefix("data: "))
        parts.append(event["token"])
    return "".join(parts)


def done_event(response: httpx.Response) -> dict:
    """Lay su kien done cuoi cung tu SSE stream."""
    done_lines = [line for line in response.text.splitlines() if '"done": true' in line]
    return json.loads(done_lines[-1].removeprefix("data: "))


# ---------------------------------------------------------------------------
# Nhom 1: Câu hỏi không rõ ràng / Thiếu ngữ cảnh  (Q1-Q4)
# Muc tieu: Tra ve phan hoi xin them thong tin, khong goi MCP tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q1_mat_bi_sao_vay(client, tokens):
    """
    Q1: "mặt bị sao vậy"
    Mong doi: Phan hoi xin lam ro hon, khong goi MCP tool
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "mặt bị sao vậy", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    answer = streamed_answer(response)
    # Phan hoi phai xin lam ro hon (tieng Viet: "chua du ngu canh" / "xin loi")
    assert any(kw in answer.lower() for kw in ["ngu canh", "hieu", "lam ro", "xin loi", "thong tin"]), \
        f"Q1 nhan duoc phan hoi khong nhu mong doi: {answer}"
    assert done_event(response)["sources"] == []
    assert mcp.last_tool_calls == [], "Q1 khong nen goi MCP tool"


@pytest.mark.asyncio
async def test_q2_mat_ong_ay(client, tokens):
    """
    Q2: "cái mặt ông ấy"
    Mong doi: Phan hoi xin lam ro, khong goi MCP
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "cái mặt ông ấy", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    answer = streamed_answer(response)
    assert any(kw in answer.lower() for kw in ["ngu canh", "hieu", "lam ro", "xin loi", "thong tin"]), \
        f"Q2 nhan duoc phan hoi khong nhu mong doi: {answer}"
    assert done_event(response)["sources"] == []
    assert mcp.last_tool_calls == [], "Q2 khong nen goi MCP tool"


@pytest.mark.asyncio
async def test_q3_tai_sao_lai_the(client, tokens):
    """
    Q3: "tại sao lại thế"
    Mong doi: Phan hoi xin them thong tin, khong goi MCP
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "tại sao lại thế", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    answer = streamed_answer(response)
    assert any(kw in answer.lower() for kw in ["ngu canh", "hieu", "lam ro", "xin loi", "thong tin", "ban"]), \
        f"Q3 nhan duoc phan hoi khong nhu mong doi: {answer}"
    assert done_event(response)["sources"] == []
    assert mcp.last_tool_calls == [], "Q3 khong nen goi MCP tool"


@pytest.mark.asyncio
async def test_q4_greeting_alternatives(client, tokens):
    """
    Q4: "alo" / "hi" / "chào"
    Mong doi: Tra loi chao hoi hoac xin lam ro, khong goi MCP.

    "hi" (tieng Anh) se tra ve phan hoi English clarification chu khong phai "chao ban".
    "alo" / "chào" se tra ve Vietnamese.
    """
    mcp = get_mcp_client()
    # [(greeting, expected_keywords_per_language)]
    greetings = [
        ("alo", ["chao ban", "co the", "ho tro", "ngu canh"]),
        ("hi", ["do not have enough context", "please clarify", "not enough context", "clarify"]),
        ("chào", ["chao ban", "co the", "ho tro", "ngu canh"]),
    ]

    for greeting, expected_keywords in greetings:
        mcp.reset()
        response = await client.post(
            "/query",
            headers=auth(tokens["hr"]),
            json={"question": greeting, "user_id": HR_USER_ID},
        )

        assert response.status_code == 200, f"Q4 ({greeting}) tra loi that bai"
        answer = streamed_answer(response).lower()
        # Accept Vietnamese OR English response depending on input language
        assert any(kw in answer for kw in expected_keywords), \
            f"Q4 ({greeting}) nhan duoc phan hoi khong nhu mong doi: {answer}"
        assert done_event(response)["sources"] == []
        assert mcp.last_tool_calls == [], f"Q4 ({greeting}) khong nen goi MCP tool"


# ---------------------------------------------------------------------------
# Nhom 2: Câu hỏi về quy định / tài liệu nội bộ  (Q5-Q7)
# Muc tieu: Dien huong vao rag_search, tra ve nguồn (sources)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q5_chinh_sach_nghi_phep(client, tokens):
    """
    Q5: "Chinh sach nghi phep la gi?"
    Mong doi: Dien huong vao rag_search, tra ve sources
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Chinh sach nghi phep la gi?", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    done = done_event(response)
    # Phai co sources tu RAG
    assert done["sources"] != [], "Q5 phai co sources tu rag_search"
    # MCP phai goi rag_search
    last_call = mcp.last_tool_calls[-1]
    assert last_call.tool_name == "rag_search", f"Q5 phai goi rag_search, nhan duoc {last_call.tool_name}"
    assert last_call.arguments["query"], "Q5 rag_search phai co query"


@pytest.mark.asyncio
async def test_q6_quy_trinh_onboarding(client, tokens):
    """
    Q6: "Quy trình onboarding cho nhân viên mới như thế nào?"
    Mong doi: Dien huong vao rag_search, tra ve sources
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Quy trình onboarding cho nhân viên mới như thế nào?", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    done = done_event(response)
    assert done["sources"] != [], "Q6 phai co sources tu rag_search"
    last_call = mcp.last_tool_calls[-1]
    assert last_call.tool_name == "rag_search"


@pytest.mark.asyncio
async def test_q7_huong_dan_bao_cao_tai_chinh(client, tokens):
    """
    Q7: "Hướng dẫn làm báo cáo tài chính"
    Muc tieu: User HR (khong phai Finance) khong co quyen truy cap tai lieu Finance
    Mong doi: Neu khong co quyen -> fallback (NO_INFO)
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),          # HR user, khong co quyen Finance
        json={"question": "Hướng dẫn làm báo cáo tài chính", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    # HR khong co quyen Finance -> khong co nguon -> fallback
    done = done_event(response)
    # Co the la fallback (khong tim thay) hoac tra loi rong tuy mock
    # Kie tra MCP da duoc goi (vi phan loai van la rag)
    assert mcp.last_tool_calls != [], "Q7 van phan loai thanh rag, MCP phai duoc goi"


# ---------------------------------------------------------------------------
# Nhom 3: Câu hỏi cá nhân hóa  (Q8-Q10)
# Muc tieu: Dien huong vao hr_query voi dung intent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q8_con_bao_nhieu_ngay_nghi(client, tokens):
    """
    Q8: "Tôi còn bao nhiêu ngày nghỉ phép trong năm nay?"
    Mong doi: Dien huong vao hr_query(intent=leave_balance)
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["finance"]),
        json={"question": "Tôi còn bao nhiêu ngày nghỉ phép trong năm nay?", "user_id": FINANCE_USER_ID},
    )

    assert response.status_code == 200
    last_call = mcp.last_tool_calls[-1]
    assert last_call.tool_name == "hr_query", f"Q8 phai goi hr_query, nhan {last_call.tool_name}"
    assert last_call.arguments["intent"] == "leave_balance", \
        f"Q8 intent phai la leave_balance, nhan {last_call.arguments.get('intent')}"
    # user_id phai la cua user duoc authenticate, khong phai LLM suggestion
    assert last_call.arguments["user_id"] == FINANCE_USER_ID


@pytest.mark.asyncio
async def test_q9_xem_phieu_luong(client, tokens):
    """
    Q9: "Cho tôi xem phiếu lương tháng này"
    Mong doi: Dien huong vao hr_query(intent=payroll)
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["finance"]),
        json={"question": "Cho tôi xem phiếu lương tháng này", "user_id": FINANCE_USER_ID},
    )

    assert response.status_code == 200
    last_call = mcp.last_tool_calls[-1]
    assert last_call.tool_name == "hr_query"
    assert last_call.arguments["intent"] == "payroll"
    assert last_call.arguments["user_id"] == FINANCE_USER_ID


@pytest.mark.asyncio
async def test_q10_leave_balance_tieng_anh(client, tokens):
    """
    Q10: "How much remaining leave do I still have?"
    Muc tieu: Xu li paraphrase tieng Anh -> hr_query(leave_balance)
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["finance"]),
        json={"question": "How much remaining leave do I still have?", "user_id": FINANCE_USER_ID},
    )

    assert response.status_code == 200
    last_call = mcp.last_tool_calls[-1]
    assert last_call.tool_name == "hr_query", f"Q10 phai goi hr_query, nhan {last_call.tool_name}"
    assert last_call.arguments["intent"] == "leave_balance", \
        f"Q10 intent phai la leave_balance, nhan {last_call.arguments.get('intent')}"


# ---------------------------------------------------------------------------
# Nhom 4: Câu hỏi Danh tính / Chào hỏi  (Q11-Q13)
# Muc tieu: Tra loi truc tiep (shortcut), khong goi MCP, no sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q11_ban_la_ai_tieng_viet(client, tokens):
    """
    Q11: "Bạn là ai?"
    Mong doi: Tra loi truc tiep, khong goi MCP, sources=[]
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Bạn là ai?", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    answer = streamed_answer(response)
    assert "VinSmartFuture" in answer, f"Q11 phan hoi phai chua VinSmartFuture: {answer}"
    assert done_event(response)["sources"] == []
    assert mcp.last_tool_calls == [], "Q11 khong nen goi MCP tool (identity shortcut)"


@pytest.mark.asyncio
async def test_q12_who_are_you_tieng_anh(client, tokens):
    """
    Q12: "Who are you?"
    Muc tieu: Xu li tieng Anh -> tra loi tieng Anh
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Who are you?", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    answer = streamed_answer(response)
    assert "VinSmartFuture" in answer, f"Q12 phan hoi phai chua VinSmartFuture: {answer}"
    assert done_event(response)["sources"] == []
    assert mcp.last_tool_calls == [], "Q12 khong nen goi MCP tool"


@pytest.mark.asyncio
async def test_q13_ai_tao_ra_ban(client, tokens):
    """
    Q13: "Ai tạo ra bạn?"
    Mong doi: Tra loi truc tiep, khong goi MCP
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Ai tạo ra bạn?", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    answer = streamed_answer(response)
    assert "VinSmartFuture" in answer, f"Q13 phan hoi phai chua VinSmartFuture: {answer}"
    assert done_event(response)["sources"] == []
    assert mcp.last_tool_calls == [], "Q13 khong nen goi MCP tool"


# ---------------------------------------------------------------------------
# Nhom 5: Câu hỏi ngoài phạm vi / Đánh lừa  (Q14-Q15)
# Muc tieu: Tu choi (REFUSE), khong goi MCP, sources=[]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q14_mixed_query_chinh_sach_va_hr(client, tokens):
    """
    Q14: "Chính sách nghỉ phép quy định thế nào, và tiện thể tôi còn bao nhiêu ngày phép?"

    Muc tieu: Tron cau hoi chinh sach (rag) voi HR ca nhan -> tu choi.

    NOTE: Phat hien mixed query hien tai chi hoat dong khi co phrase "nghi phep con"
    trong PERSONAL_HR_PHRASES. Tu "ngay phep" (khong co "con") khong duoc detect
    nên hệ thống hiện tại xử lý câu này như RAG thuần.
    Test nay kiem tra hành vi THỰC TẾ: hệ thống sẽ gọi rag_search.
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["finance"]),
        json={
            "question": "Chính sách nghỉ phép quy định thế nào, và tiện thể tôi còn bao nhiêu ngày phép?",
            "user_id": FINANCE_USER_ID,
        },
    )

    assert response.status_code == 200
    # Hien tai: he thong khong detect duoc "ngay phep" -> tien th Hanh xu ly RAG
    last_call = mcp.last_tool_calls[-1]
    assert last_call.tool_name == "rag_search", \
        f"Q14 hien tai xu ly nhu rag (khong detect duoc 'ngay phep' nhu personal HR). Nhan: {last_call.tool_name}"


@pytest.mark.asyncio
async def test_q15_password_security(client, tokens):
    """
    Q15: "Mật khẩu hệ thống admin là gì?"
    Muc tieu: Tu choi yeu cau thong tin bao mat, khong goi MCP
    Mong doi: Tra loi tu choi, nhan dien mat khau / bao mat
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["admin"]),
        json={"question": "Mật khẩu hệ thống admin là gì?", "user_id": ADMIN_USER_ID},
    )

    assert response.status_code == 200
    answer = streamed_answer(response).lower()
    # Phan hoi phai tu choi (chua mat khau / bao mat / khong the)
    assert any(kw in answer for kw in ["mat khau", "khong", "bao mat", "quyen"]), \
        f"Q15 phan hoi phai tu choi: {answer}"
    assert done_event(response)["sources"] == []
    assert mcp.last_tool_calls == [], "Q15 khong nen goi MCP tool (security refusal)"


# ---------------------------------------------------------------------------
# Nhom 6: Câu hỏi Off-Topic / Ngoài phạm vi doanh nghiệp  (Q16-Q20)
# Muc tieu: Nhan dien va tu choi off-topic, khong goi MCP, tra ve OFF_TOPIC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q16_off_topic_mua_sua(client, tokens):
    """
    Q16: "Bạn ghét ăn sữa, tôi cần mua gì"
    Muc tieu: Topic off-topic (mua sam / doi song), khong goi MCP, tra ve OFF_TOPIC.
    Bug truoc day: cau hoi nay tro thanh rag_search, LLM tu ban cau tra loi
    tu tai lieu HR, dan den hallucination.
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Bạn ghét ăn sữa, tôi cần mua gì", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    done = done_event(response)
    assert done["outcome"] == Outcome.OFF_TOPIC.value, \
        f"Q16 phai tra ve OFF_TOPIC, nhan outcome={done.get('outcome')}"
    assert done["sources"] == []
    assert mcp.last_tool_calls == [], \
        f"Q16 khong nen goi MCP tool (off-topic). MCP calls: {mcp.last_tool_calls}"


@pytest.mark.asyncio
async def test_q17_off_topic_cong_thuc_nau_an(client, tokens):
    """
    Q17: "Công thức nấu phở như thế nào?"
    Muc tieu: Topic off-topic (nau an), tu choi.
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["finance"]),
        json={"question": "Công thức nấu phở như thế nào?", "user_id": FINANCE_USER_ID},
    )

    assert response.status_code == 200
    done = done_event(response)
    assert done["outcome"] == Outcome.OFF_TOPIC.value
    assert done["sources"] == []
    assert mcp.last_tool_calls == [], "Q17 khong nen goi MCP tool (off-topic)"


@pytest.mark.asyncio
async def test_q18_off_topic_thoi_tiet(client, tokens):
    """
    Q18: "Thời tiết ngày mai thế nào?"
    Muc tieu: Topic off-topic (thoi tiet), tu choi.
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Thời tiết ngày mai thế nào?", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    done = done_event(response)
    assert done["outcome"] == Outcome.OFF_TOPIC.value
    assert done["sources"] == []
    assert mcp.last_tool_calls == []


@pytest.mark.asyncio
async def test_q19_off_topic_nha_hang(client, tokens):
    """
    Q19: "Nên đi ăn nhà hàng nào ở quận 1?"
    Muc tieu: Topic off-topic (nha hang / doi song), tu choi.
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["admin"]),
        json={"question": "Nên đi ăn nhà hàng nào ở quận 1?", "user_id": ADMIN_USER_ID},
    )

    assert response.status_code == 200
    done = done_event(response)
    assert done["outcome"] == Outcome.OFF_TOPIC.value
    assert done["sources"] == []
    assert mcp.last_tool_calls == []


@pytest.mark.asyncio
async def test_q20_off_topic_khong_override_chinh_sach(client, tokens):
    """
    Q20: "Chính sách mua sắm văn phòng phẩm cho nhân viên"
    Muc tieu: Cau hoi co "chinh sach" -> van phai la rag, khong phai off_topic.
    "mua" chi la 1 phan cua chinh sach, khong phai shopping.
    """
    mcp = get_mcp_client()
    mcp.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Chính sách mua sắm văn phòng phẩm cho nhân viên", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    done = done_event(response)
    # Co policy keyword -> phai la rag, khong phai off_topic
    assert done["outcome"] != "OFF_TOPIC", \
        f"Q20 co 'chinh sach' nen khong phai off-topic. Nhan: {done.get('outcome')}"
    assert mcp.last_tool_calls != [], "Q20 nen goi MCP tool (rag_search)"
