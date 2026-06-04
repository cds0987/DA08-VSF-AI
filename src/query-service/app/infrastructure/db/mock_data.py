from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.application.ports import AuthenticatedUser
from app.infrastructure.auth.auth_service import MOCK_TOKENS


@dataclass(frozen=True)
class MockDocument:
    id: str
    name: str
    classification: str
    department: str
    caption: str
    heading_path: list[str]
    section_content: str
    source_s3_uri: str
    score: float
    allowed_departments: list[str] = field(default_factory=list)
    allowed_user_ids: list[str] = field(default_factory=list)


MOCK_DOCUMENTS: list[MockDocument] = [
    MockDocument(
        id="dddddddd-0001-4000-8000-000000000001",
        name="Onboarding Handbook 2026.md",
        classification="public",
        department="General",
        caption="Quy trình onboarding nhân viên mới",
        heading_path=["Onboarding", "Ngày đầu tiên"],
        section_content=(
            "Nhân viên mới cần hoàn tất hồ sơ, kích hoạt tài khoản nội bộ, "
            "đọc quy định bảo mật và tham gia buổi giới thiệu công ty."
        ),
        source_s3_uri="s3://rag-chatbot-docs/public/onboarding-handbook-2026.md",
        score=0.86,
    ),
    MockDocument(
        id="dddddddd-0002-4000-8000-000000000002",
        name="Chinh_sach_nghi_phep_2026.pdf",
        classification="internal",
        department="HR",
        caption="Chính sách nghỉ phép năm",
        heading_path=["HR", "Nghỉ phép", "Số ngày nghỉ"],
        section_content=(
            "Mỗi nhân viên chính thức có 12 ngày nghỉ phép năm. "
            "Ngày nghỉ chưa dùng cần được đăng ký và phê duyệt trên hệ thống HR."
        ),
        source_s3_uri="s3://rag-chatbot-docs/internal/chinh-sach-nghi-phep-2026.pdf",
        score=0.92,
    ),
    MockDocument(
        id="dddddddd-0003-4000-8000-000000000003",
        name="Finance_Report_Guideline.xlsx",
        classification="secret",
        department="Finance",
        caption="Quy định lập báo cáo tài chính nội bộ",
        heading_path=["Finance", "Reporting", "Approval"],
        section_content=(
            "Báo cáo tài chính nội bộ chỉ được chia sẻ trong phòng Finance. "
            "Mọi file dự thảo phải được trưởng bộ phận phê duyệt trước khi gửi."
        ),
        source_s3_uri="s3://rag-chatbot-docs/secret/finance-report-guideline.xlsx",
        score=0.89,
        allowed_departments=["Finance"],
    ),
    MockDocument(
        id="dddddddd-0004-4000-8000-000000000004",
        name="Executive_Compensation_Top_Secret.pdf",
        classification="top_secret",
        department="Admin",
        caption="Tài liệu tuyệt mật cho ban điều hành",
        heading_path=["Executive", "Compensation"],
        section_content=(
            "Tài liệu này chỉ dành cho người được chỉ định trong danh sách "
            "allowed_user_ids và không được đưa vào trace chi tiết."
        ),
        source_s3_uri="s3://rag-chatbot-docs/top-secret/executive-compensation.pdf",
        score=0.94,
        allowed_user_ids=["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"],
    ),
]


MOCK_HR_DATA: dict[str, dict[str, object]] = {
    MOCK_TOKENS["mock-user-hr"].id: {
        "leave_balance": {
            "annual_leave_total": 12,
            "annual_leave_used": 4,
            "annual_leave_remaining": 8,
            "sick_leave_total": 10,
            "sick_leave_used": 1,
        },
        "leave_requests": [
            {
                "id": "leave-hr-001",
                "leave_type": "annual",
                "start_date": "2026-06-10",
                "end_date": "2026-06-11",
                "days_count": 2,
                "status": "approved",
            }
        ],
        "payroll": {
            "period": "2026-05",
            "gross_salary": 25000000,
            "deductions": 2100000,
            "net_salary": 22900000,
        },
    },
    MOCK_TOKENS["mock-user-finance"].id: {
        "leave_balance": {
            "annual_leave_total": 12,
            "annual_leave_used": 7,
            "annual_leave_remaining": 5,
            "sick_leave_total": 10,
            "sick_leave_used": 0,
        },
        "leave_requests": [
            {
                "id": "leave-fin-001",
                "leave_type": "annual",
                "start_date": "2026-06-18",
                "end_date": "2026-06-18",
                "days_count": 1,
                "status": "pending",
            }
        ],
        "payroll": {
            "period": "2026-05",
            "gross_salary": 30000000,
            "deductions": 2800000,
            "net_salary": 27200000,
        },
    },
}


def mock_users() -> list[AuthenticatedUser]:
    return list(MOCK_TOKENS.values())


def utcnow() -> datetime:
    return datetime.now(UTC)
