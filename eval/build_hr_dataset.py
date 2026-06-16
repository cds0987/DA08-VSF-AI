#!/usr/bin/env python3
"""Replace first 18 policy questions with HR questions from employee handbooks."""
import json
from pathlib import Path

GOLDEN_QA = Path("eval/dataset/dataset_new/goldenqa/golden_qa.jsonl")

CNHC = "CNHC_Employee_Handbook.pdf"
PCI  = "PCI_Employee_Handbook.pdf"
EMP  = "Employee-Handbook-for-Nonprofits-and-Small-Businesses.pdf"
NQLD = "Mau-noi-quy-lao-dong-2024.docx"

NEW_QA = [
    {
        "question_id": "qa_hr_001",
        "question": "Yêu cầu thiết lập văn phòng tại nhà khi làm việc từ xa là gì?",
        "golden_answer": (
            "Nhân viên cần thiết lập văn phòng tại nhà ở khu vực yên tĩnh, đủ ánh sáng, "
            "ít bị xao nhãng, có kết nối internet ổn định, laptop, headset và webcam. "
            "Nên dùng nội thất công thái học và kiểm tra trước thiết bị, âm thanh, camera "
            "trước các cuộc họp."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_002",
        "question": "Chính sách hút thuốc tại nơi làm việc là gì?",
        "golden_answer": (
            "Hút thuốc bị cấm trong toàn bộ khu vực làm việc, bao gồm cả khuôn viên "
            "bên ngoài tòa nhà."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_003",
        "question": "Chính sách mạng xã hội áp dụng với nhân viên như thế nào?",
        "golden_answer": (
            "Chính sách áp dụng với mọi trường hợp sử dụng mạng xã hội dù dùng tài khoản "
            "công ty hay tài khoản cá nhân. Khi đại diện cho công ty phải tuân thủ quy định "
            "về bảo mật, bản quyền, nhãn hiệu. Với tài khoản cá nhân không được tiết lộ "
            "thông tin mật của công ty."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_004",
        "question": "Quy định bảo mật dữ liệu cá nhân của nhân viên là gì?",
        "golden_answer": (
            "Nhân viên chỉ được truy cập dữ liệu cá nhân khi cần cho công việc và được ủy "
            "quyền. Phải dùng mật khẩu mạnh, không chia sẻ mật khẩu, khóa màn hình khi rời "
            "chỗ ngồi, lưu trữ và hủy dữ liệu đúng cách, không chia sẻ với người không có "
            "thẩm quyền."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_005",
        "question": "Vi phạm bảo mật dữ liệu sẽ bị xử lý như thế nào?",
        "golden_answer": (
            "Vi phạm bảo mật có thể bị xem là hành vi kỷ luật và dẫn đến chấm dứt hợp đồng "
            "lao động. Việc truy cập hoặc tiết lộ dữ liệu nhân viên không đúng cách là vi "
            "phạm dữ liệu và cần được báo cáo ngay lập tức."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_006",
        "question": "Chính sách chống phân biệt đối xử của công ty quy định gì?",
        "golden_answer": (
            "Công ty duy trì môi trường làm việc không quấy rối và cấm phân biệt đối xử "
            "trái pháp luật cũng như trả đũa người báo cáo vi phạm. Người vi phạm có thể "
            "bị xử lý kỷ luật, thậm chí chấm dứt hợp đồng."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_007",
        "question": "Nhân viên có thể bị chấm dứt hợp đồng trong những trường hợp nào?",
        "golden_answer": (
            "Chấm dứt hợp đồng có thể xảy ra khi vi phạm nghiêm trọng, vi phạm nghĩa vụ "
            "và trách nhiệm làm ảnh hưởng đến lợi ích công ty, hoặc theo chính sách kỷ "
            "luật của công ty."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_008",
        "question": "Chính sách hoàn trả chi phí đi lại công tác là gì?",
        "golden_answer": (
            "Chi phí đi lại được hoàn trả khi phù hợp với chính sách. Nhân viên nên ưu tiên "
            "phương tiện công cộng hoặc phương án hiệu quả nhất về chi phí. Taxi, vé tàu, "
            "vé máy bay và khách sạn cần có điều kiện phù hợp và phê duyệt trước; tất cả "
            "chi phí phải có hóa đơn hợp lệ."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_009",
        "question": "Quy định khi dùng xe cá nhân cho công việc?",
        "golden_answer": (
            "Việc dùng xe cá nhân cho công việc phải được phê duyệt trước và đáp ứng yêu "
            "cầu về bằng lái, bảo hiểm và tình trạng xe. Chi phí đi lại được hoàn trả dựa "
            "trên quãng đường ngắn hơn giữa nhà và nơi làm việc chính."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_010",
        "question": "Nhân viên có quyền riêng tư khi sử dụng hệ thống liên lạc điện tử của công ty không?",
        "golden_answer": (
            "Nhân viên không có quyền riêng tư khi sử dụng hệ thống của công ty. Công ty có "
            "thể truy cập và giám sát email, tệp và các hệ thống bất cứ lúc nào mà không "
            "cần báo trước."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_011",
        "question": "Quy định về xung đột lợi ích khi nhận việc bên ngoài?",
        "golden_answer": (
            "Nhân viên phải báo cáo và được chấp thuận bằng văn bản trước khi nhận công "
            "việc bên ngoài để tránh xung đột lợi ích. Không báo cáo có thể dẫn đến sa "
            "thải. Xung đột gồm làm việc cho đối thủ, khách hàng hiện tại hoặc các công "
            "việc cạnh tranh."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_012",
        "question": "Yêu cầu an toàn lao động tại nơi làm việc là gì?",
        "golden_answer": (
            "Nhân viên phải tuân thủ các quy định an toàn lao động, làm việc an toàn, "
            "báo ngay mọi tai nạn hoặc chấn thương cho quản lý, không đùa giỡn trong khu "
            "vực làm việc, và báo cáo các điều kiện hoặc hành vi không an toàn."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_013",
        "question": "Nhân viên phải làm gì trong trường hợp khẩn cấp tại nơi làm việc?",
        "golden_answer": (
            "Nhân viên cần báo cho quản lý biết vị trí và tình huống; phải có phương tiện "
            "liên lạc khẩn cấp; biết lối thoát hiểm gần nhất và quy trình sơ tán của công "
            "ty. Phải báo ngay cho quản lý mọi sự cố và hoàn thành mẫu báo cáo sự cố."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_014",
        "question": "Chính sách về rượu và chất gây nghiện tại nơi làm việc?",
        "golden_answer": (
            "Lạm dụng rượu và ma túy có thể làm giảm hiệu suất, ảnh hưởng phán đoán, tăng "
            "rủi ro an toàn và dẫn đến kỷ luật kể cả sa thải. Nhân viên không được sử dụng "
            "ma túy bất hợp pháp trong nơi làm việc và nên tìm hỗ trợ chuyên môn nếu có "
            "vấn đề."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_015",
        "question": "Trang phục đi làm tại văn phòng phải tuân thủ quy định gì?",
        "golden_answer": (
            "Trang phục, tóc tai và vệ sinh cá nhân phải phù hợp với môi trường làm việc "
            "chuyên nghiệp. Không được mặc áo hở vai, quần jeans, đồ thể thao, quần shorts, "
            "dép xỏ ngón, áo T-shirt hoặc mũ bóng chày."
        ),
        "doc_id": PCI,
    },
    {
        "question_id": "qa_hr_016",
        "question": "Nhân viên toàn thời gian bắt đầu được hưởng phúc lợi từ khi nào?",
        "golden_answer": (
            "Nhân viên toàn thời gian đủ điều kiện tham gia gói phúc lợi từ ngày đầu tiên "
            "của tháng sau ngày bắt đầu làm việc. Đăng ký hoặc chỉnh sửa phúc lợi chỉ được "
            "thực hiện trong thời gian tuyển dụng hoặc open enrollment."
        ),
        "doc_id": EMP,
    },
    {
        "question_id": "qa_hr_017",
        "question": "Công ty xử lý các trường hợp quấy rối tại nơi làm việc như thế nào?",
        "golden_answer": (
            "Công ty không dung thứ cho hành vi quấy rối giữa nhân viên hoặc từ người "
            "ngoài. Nếu bị quấy rối, nhân viên nên báo cáo ngay cho quản lý hoặc bộ phận "
            "HR. Người vi phạm có thể bị kỷ luật hoặc chấm dứt hợp đồng."
        ),
        "doc_id": CNHC,
    },
    {
        "question_id": "qa_hr_018",
        "question": "Nhân viên được hưởng bao nhiêu ngày nghỉ phép có lương mỗi năm?",
        "golden_answer": (
            "Nhân viên chính thức được 12 ngày phép năm, tối đa 5 ngày có thể chuyển sang "
            "năm sau. Nghỉ ốm có lương tối đa 30 ngày mỗi năm khi có giấy bác sĩ."
        ),
        "doc_id": NQLD,
    },
]


def build_entry(qa: dict) -> dict:
    return {
        "question_id": qa["question_id"],
        "question": qa["question"],
        "golden_answer": qa["golden_answer"],
        "ground_truth": qa["golden_answer"],
        "doc_id": qa["doc_id"],
        "source_doc": qa["doc_id"],
        "expected_chunk_ids": [],
        "expected_chunk_id": None,
        "expected_page": None,
        "expected_section": None,
        "topic": None,
        "question_type": None,
        "difficulty": None,
    }


def main() -> None:
    lines = GOLDEN_QA.read_text(encoding="utf-8").splitlines(keepends=True)
    print(f"Original file: {len(lines)} lines")

    # Find the first 18 non-OOS lines (they all start with qa_policy_0301)
    # We'll just replace lines 0-17 directly
    policy_0301_count = sum(
        1 for l in lines[:18]
        if json.loads(l).get("question_id", "").startswith("qa_policy_0301")
    )
    print(f"Policy 0301 questions in first 18 lines: {policy_0301_count}")

    new_lines = [
        json.dumps(build_entry(qa), ensure_ascii=False) + "\n"
        for qa in NEW_QA
    ]
    # Replace first 18 lines with new HR questions
    updated = new_lines + lines[18:]
    GOLDEN_QA.write_text("".join(updated), encoding="utf-8")
    print(f"Updated file: {len(updated)} lines")
    print("First 3 new lines:")
    for line in updated[:3]:
        d = json.loads(line)
        print(f"  {d['question_id']} | {d['question'][:60]}")
    print("Lines 18-20 (unchanged):")
    for line in updated[18:21]:
        d = json.loads(line)
        print(f"  {d['question_id']} | {d['question'][:60]}")
    print("Last 3 lines (OOS, unchanged):")
    for line in updated[-3:]:
        d = json.loads(line)
        print(f"  {d['question_id']} | {d.get('question_type','')} | {d['question'][:50]}")


if __name__ == "__main__":
    main()
