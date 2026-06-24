"""Chung cho bài load-test 20 concurrent user (TTFT + độ đều token + công bằng giữa user).

Không phải code hệ thống — chỉ là harness test. Credential tái dùng đúng bộ đã có trong repo
(eval/playwright-eval/drive_chat.py, eval/long-adv/target_client.py). Có thể override qua env:
  LOAD_BASE, LOAD_ADMIN_EMAIL, LOAD_ADMIN_PW, LOAD_USER_PW
"""
from __future__ import annotations

import os
import time

BASE = os.environ.get("LOAD_BASE", "https://vsfchat.cloud")
USER_API = f"{BASE}/api/user"
QUERY_API = f"{BASE}/api/query"

# Admin (đã có sẵn trong repo) — để tạo 20 user test qua POST /api/user/users.
ADMIN_EMAIL = os.environ.get("LOAD_ADMIN_EMAIL", "admin@company.com")
ADMIN_PW = os.environ.get("LOAD_ADMIN_PW", "DemoAdminPassword123!")

# 20 user test sẽ được seed (idempotent). Mỗi user 1 phiên -> né cap 3-SSE/user.
N_USERS = int(os.environ.get("LOAD_N_USERS", "20"))
USER_PW = os.environ.get("LOAD_USER_PW", "LoadTest123!")
USER_EMAIL = lambda i: f"loadtest{i:02d}@company.com"  # noqa: E731

# Bao nhiêu trong N chạy bằng TRÌNH DUYỆT THẬT (Playwright) — phần còn lại chạy SSE-HTTP.
N_BROWSERS = int(os.environ.get("LOAD_N_BROWSERS", "4"))

# Câu hỏi đa dạng (HR + chính sách) -> ép đúng đường nặng RAG/HR -> think/answer (deepseek@OpenRouter).
# Mỗi user 1 câu khác nhau: thực tế hơn + tránh cache trùng.
QUESTIONS = [
    "Tôi còn bao nhiêu ngày phép năm nay?",
    "Chính sách nghỉ phép năm của công ty quy định thế nào?",
    "Nghỉ kết hôn được nghỉ mấy ngày có lương?",
    "Công tác phí đi nước ngoài được thanh toán bao nhiêu một ngày?",
    "Quy định về làm thêm giờ và cách tính lương OT ra sao?",
    "Chế độ thai sản cho nhân viên nữ gồm những gì?",
    "Nghỉ ốm cần thủ tục và giấy tờ gì?",
    "Phụ cấp ăn trưa và đi lại hiện tại là bao nhiêu?",
    "Quy trình xin nghỉ phép trên hệ thống thế nào?",
    "Chính sách thưởng Tết và lương tháng 13 quy định ra sao?",
    "Nhân viên thử việc có được hưởng phép năm không?",
    "Bảo hiểm sức khỏe công ty chi trả những hạng mục nào?",
    "Quy định về trang phục và giờ làm việc tại văn phòng?",
    "Khi nghỉ việc cần bàn giao và báo trước bao nhiêu ngày?",
    "Chính sách đào tạo và hỗ trợ học phí cho nhân viên?",
    "Phụ cấp trách nhiệm cho cấp quản lý được tính thế nào?",
    "Nghỉ tang chế (hiếu hỉ) được nghỉ mấy ngày?",
    "Quy định về remote/làm việc từ xa hiện nay ra sao?",
    "Cách tính trợ cấp thôi việc khi nghỉ theo luật?",
    "Chính sách đánh giá hiệu suất (KPI) định kỳ thế nào?",
]


def parse_sse_line(line: str):
    """1 dòng SSE -> dict event hoặc None. Chấp nhận 'data: {...}'."""
    import json
    if not line or not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        return json.loads(payload)
    except Exception:
        return None


def classify_event(ev: dict):
    """(kind, value) với kind ∈ {answer, thought, model, status, done, other}.

    - answer  : token câu trả lời cuối (phase=generating hoặc token trần, KHÔNG phải thought)
    - thought : reasoning panel ('đang suy nghĩ') — phase thinking/thought
    - model   : phase model_used -> model thật (bắt save_mode degrade gpt-4o-mini)
    - done    : kết thúc stream
    """
    if ev.get("done") is True:
        return ("done", ev)
    phase = ev.get("phase")
    if phase == "model_used":
        return ("model", ev.get("model") or ev.get("node"))
    if phase in ("thinking", "thought"):
        return ("thought", ev.get("token") or ev.get("text") or "")
    tok = ev.get("token")
    if tok:
        return ("answer", tok)
    if phase in ("acting", "observing", "plan", "step"):
        return ("status", phase)
    return ("other", phase)


def now() -> float:
    return time.time()
