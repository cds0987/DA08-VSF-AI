# -*- coding: utf-8 -*-
"""Multi-subagent benchmark (~150 queries) — câu compound/so-sánh/đa-khía-cạnh ÉP planner
fan-out >=2 worker song song. Mục tiêu: đo latency KHI fan-out THẬT kích hoạt (campaign #1
chỉ 15% câu có >1 worker). Grounded trên corpus thật (Vintravel/MeKong/BlueOcean handbooks,
Bộ luật LĐ 2019, VSF lương, claude_test_hr_policy, doc ảnh).

Mỗi item: id, task_type=multiagent, subtype, q, expect, expect_min_workers.
"""
DATA = []
def add(sub, q, expect, mw=2):
    DATA.append({"id": f"ma-{len(DATA)+1:03d}", "task_type": "multiagent", "subtype": sub,
                 "q": q, "expect": expect, "expect_min_workers": mw, "expect_outcome": 5})

# A. Cross-company comparison — mỗi công ty = 1 retrieval riêng (ép song song) ──────────
A = [
 "So sánh thang bảng lương giữa Vintravel, MeKong và BlueOcean.",
 "Số ngày phép cộng thêm theo thâm niên ở Vintravel, MeKong và BlueOcean khác nhau thế nào?",
 "So sánh hạn mức phê duyệt chi tiêu theo cấp giữa MeKong và BlueOcean.",
 "Tỷ lệ luân chuyển nhân sự theo khối của Vintravel so với MeKong ra sao?",
 "Cơ cấu chi phí 2025 theo khoản mục của BlueOcean và Vintravel khác nhau chỗ nào?",
 "Giờ đào tạo bình quân theo khối ở MeKong so với Vintravel thế nào?",
 "Quy trình duyệt công tác ở Vintravel và BlueOcean có gì khác nhau?",
 "So sánh xếp hạng rủi ro trọng yếu (Phụ lục R) giữa Vintravel và MeKong.",
 "Doanh thu và chi phí theo quý 2025 của BlueOcean so với MeKong khác nhau ra sao?",
 "Nhân sự theo phòng ban của Vintravel và BlueOcean khác nhau thế nào?",
 "So sánh chính sách thâm niên giữa Vintravel và MeKong.",
 "Hạn mức phê duyệt chi tiêu của Vintravel, MeKong, BlueOcean — công ty nào cao nhất?",
 "So sánh hệ thống thang bảng lương của cả ba công ty MeKong, Vintravel, BlueOcean.",
 "Phép cộng thêm thâm niên trên 10 năm ở ba công ty khác nhau bao nhiêu ngày?",
 "So sánh cơ cấu chi phí và tỷ lệ luân chuyển nhân sự giữa MeKong và BlueOcean.",
]
for q in A: add("compare_company", q, "fan-out theo từng công ty; nêu khác biệt grounded từng handbook", 2)

# B. Multi-topic policy bundle — mỗi chủ đề = 1 retrieval ──────────────────────────────
B = [
 "Cho tôi biết cả chính sách nghỉ phép năm, chính sách thai sản, và quy định làm thêm giờ.",
 "Tóm tắt 3 việc: thời hạn báo trước khi nghỉ việc, mức khấu trừ lương tối đa, và phụ cấp làm đêm.",
 "Giải thích quy định kỷ luật lao động, quy định bảo mật thông tin, và quy định đi muộn.",
 "Nêu chính sách lương thử việc, các khoản khấu trừ bắt buộc, và cách tính thuế TNCN.",
 "Cho tôi quy định về nghỉ kết hôn, nghỉ tang, và nghỉ việc riêng có lương.",
 "Tóm tắt: thời giờ làm việc tối đa, nghỉ hằng tuần, và nghỉ lễ trong năm.",
 "Giải thích chế độ thai sản, chế độ ốm đau, và chế độ nghỉ chăm con.",
 "Nêu quy định về hợp đồng lao động, thử việc, và đào tạo nghề.",
 "Cho tôi biết mức lương tối thiểu, chế độ nâng lương, và quy định tạm ứng lương.",
 "Tóm tắt quy định bảo hiểm xã hội, bảo hiểm y tế, và bảo hiểm thất nghiệp.",
 "Giải thích quy trình tuyển dụng, đánh giá thử việc, và thưởng giới thiệu.",
 "Nêu quy định về tranh chấp lao động, thỏa ước lao động tập thể, và đình công.",
 "Cho tôi chính sách phép năm, phép thâm niên, và quy định chuyển phép sang năm sau.",
 "Tóm tắt: quy định PCCC, quy định an ninh ra vào, và quy định sử dụng tài sản chung.",
 "Giải thích quy trình nghỉ việc, bàn giao tài sản, và quy định sa thải.",
 "Nêu quy định sử dụng email nội bộ, họp trực tuyến, và công cụ AI.",
 "Cho tôi biết chính sách tiếp khách, tổ chức sự kiện nội bộ, và quản lý quà tặng.",
 "Tóm tắt quy định mua sắm vật tư, sử dụng phòng họp, và sử dụng phương tiện công ty.",
 "Giải thích quy chế đánh giá hiệu suất, KPI, và quy định khen thưởng.",
 "Nêu quy định quản lý văn bản, lưu trữ hồ sơ, và tiêu hủy tài liệu.",
 "Cho tôi cả chính sách lương, chính sách phép, và chính sách bảo hiểm của công ty.",
 "Tóm tắt: nghỉ thai sản 6 tháng, sinh đôi cộng thêm, và chế độ đi làm sớm sau sinh.",
 "Giải thích quyền đơn phương chấm dứt HĐ của NLĐ và của NSDLĐ.",
 "Nêu quy định làm thêm giờ ngày thường, ngày nghỉ, và ngày lễ.",
 "Cho tôi quy định khấu trừ lương, tạm ứng lương, và trả lương ngừng việc.",
]
for q in B: add("multi_topic", q, "fan-out theo từng chủ đề; trả lời đủ MỌI khía cạnh được hỏi", 2)

# C. HR-personal + policy combo — hr_lookup SONG SONG rag_retrieve ───────────────────────
C = [
 "Tôi còn bao nhiêu phép, và chính sách chuyển phép sang năm sau thế nào?",
 "Cho tôi số phép còn lại và giải thích cách tính phép theo thâm niên.",
 "Tôi còn mấy ngày phép, và nếu nghỉ thai sản thì chế độ ra sao?",
 "Số dư phép của tôi là bao nhiêu, và quy định nghỉ phép năm của công ty thế nào?",
 "Tôi còn bao nhiêu ngày ốm, và chế độ ốm đau theo luật quy định ra sao?",
 "Cho tôi biết phép còn lại và quy định về nghỉ không lương.",
 "Tôi đã nghỉ mấy ngày rồi, và phép năm tối đa được bao nhiêu ngày?",
 "Số phép còn lại của tôi, và nếu xin nghỉ cưới thì được thêm mấy ngày?",
 "Tôi còn bao nhiêu phép, và muốn xin nghỉ thì báo trước bao lâu?",
 "Cho tôi quỹ phép hiện tại và chính sách phụ cấp làm đêm.",
 "Tôi còn mấy ngày phép, và lương thử việc tính thế nào?",
 "Số ngày phép của tôi, và quy định khấu trừ lương khi nghỉ quá phép?",
 "Tôi còn bao nhiêu phép năm, và quy trình duyệt đơn nghỉ ra sao?",
 "Cho tôi biết phép còn lại và chính sách thưởng cuối năm.",
 "Tôi còn mấy ngày phép, đồng thời giải thích quyền lợi bảo hiểm xã hội của tôi.",
]
for q in C: add("hr_plus_policy", q, "hr_lookup (số cá nhân) + rag_retrieve (chính sách) — trả CẢ HAI", 2)

# D. Multi-aspect single process — đa khía cạnh, có thể fan-out ─────────────────────────
D = [
 "Quy trình nghỉ việc gồm thời hạn báo trước, bàn giao tài sản và trợ cấp — nêu cả ba.",
 "Giải thích quy trình tuyển dụng từ ứng tuyển, thử việc đến thưởng giới thiệu.",
 "Quy trình kỷ luật: hình thức xử lý, thời hiệu, và quyền khiếu nại của NLĐ.",
 "Cho tôi quy trình quản lý dự án: nghiệm thu, bàn giao sản phẩm và kiểm soát rủi ro.",
 "Quy trình xử lý khiếu nại nội bộ: tiếp nhận, điều tra, và phòng chống quấy rối.",
 "Giải thích quy trình chăm sóc khách hàng: tiếp nhận yêu cầu, hỗ trợ và xử lý khiếu nại.",
 "Quy trình mua sắm: đề nghị, phê duyệt theo hạn mức, và nghiệm thu.",
 "Cho tôi quy trình báo cáo sự cố vận hành: phát hiện, ứng cứu khẩn cấp và khắc phục.",
 "Quy trình quản lý nhà cung cấp: lựa chọn, ký hợp đồng và đánh giá dịch vụ thuê ngoài.",
 "Giải thích quy trình quản lý rủi ro: nhận diện, kiểm soát nội bộ và kiểm tra tuân thủ.",
 "Quy trình đặt phòng họp: đặt lịch, check-in, và xử lý no-show.",
 "Cho tôi quy trình sử dụng phương tiện công ty: đặt xe, xăng xe và bãi đỗ.",
 "Quy trình bảo hiểm: tham gia BHXH/BHYT/BHTN và bảo hộ lao động.",
 "Giải thích quy chế đánh giá hiệu suất: mục tiêu công việc, KPI và xếp loại.",
 "Quy trình quản lý tài sản: vệ sinh khu vực chung, tiết kiệm năng lượng và bảo quản.",
]
for q in D: add("multi_aspect", q, "nêu đủ các khía cạnh/bước được hỏi, grounded", 2)

# E. Cross-domain compound — 2 lĩnh vực khác nhau (ép 2 retrieval) ───────────────────────
E = [
 "So sánh quy định sử dụng email nội bộ và quy định bảo mật tài liệu.",
 "Bảo hiểm vật chất xe ô tô PTI và chế độ bảo hiểm xã hội của công ty khác nhau thế nào?",
 "Quy định PCCC và quy định an ninh kiểm soát ra vào khác nhau ở điểm nào?",
 "So sánh chính sách lương của VSF và thang bảng lương trong sổ tay Vintravel.",
 "Quy định kỷ luật lao động và quy trình xử lý khiếu nại liên hệ với nhau thế nào?",
 "So sánh nghỉ thai sản theo Bộ luật lao động và theo nội quy lao động mẫu.",
 "Thuế TNCN của hộ kinh doanh và khấu trừ thuế TNCN từ lương nhân viên khác nhau ra sao?",
 "So sánh quy định làm thêm giờ trong Bộ luật và trong nội quy công ty.",
 "Quy định tuyển dụng kỹ thuật của Brother và quy trình tuyển dụng nội bộ VSF khác nhau thế nào?",
 "So sánh điều kiện bảo hành sản phẩm Brother và điều kiện tham gia bảo hiểm xe PTI.",
 "Nội quy văn phòng và quy định sử dụng điện trong tài liệu ảnh nói gì khác nhau?",
 "So sánh chính sách phép năm của VSF và quy định phép trong Bộ luật lao động.",
 "Quy định bảo mật thông tin và quy định sử dụng công cụ AI có gì chồng lấn?",
 "So sánh hạn mức chi tiêu của MeKong và chính sách quản lý nhà cung cấp.",
 "Chế độ thai sản và chế độ ốm đau trong tài liệu nội bộ khác nhau thế nào?",
]
for q in E: add("cross_domain", q, "2 lĩnh vực -> 2 retrieval song song; nêu khác biệt", 2)

# F. Heavy 3+ way — ép fan-out >=3 ───────────────────────────────────────────────────────
F = [
 "So sánh đồng thời thang lương, phép thâm niên và hạn mức chi tiêu của Vintravel, MeKong, BlueOcean.",
 "Cho tôi biết phép còn lại của tôi, chính sách phép năm, và quy trình duyệt đơn nghỉ.",
 "Tóm tắt 4 việc: lương thử việc, khấu trừ bắt buộc, phụ cấp làm đêm, và thưởng cuối năm.",
 "So sánh nghỉ phép, nghỉ thai sản và nghỉ ốm giữa nội quy công ty và Bộ luật lao động.",
 "Nêu quy trình nghỉ việc, quy trình kỷ luật và quy trình khiếu nại cùng lúc.",
 "Cho tôi tỷ lệ luân chuyển nhân sự, cơ cấu chi phí và giờ đào tạo của cả 3 công ty.",
 "Giải thích cùng lúc: BHXH, BHYT, BHTN, và cách tính thuế TNCN từ lương.",
 "So sánh hạn mức phê duyệt chi tiêu, quy trình duyệt công tác và quản lý nhà cung cấp.",
 "Tóm tắt chế độ thai sản, sinh đôi cộng thêm, đi làm sớm, và chế độ cho lao động nam.",
 "Cho tôi phép còn lại, phép thâm niên áp dụng cho tôi, và chính sách chuyển phép năm sau.",
 "So sánh quy định làm thêm giờ, nghỉ hằng tuần và nghỉ lễ theo luật và nội quy.",
 "Nêu quy trình tuyển dụng, đánh giá thử việc, KPI và khen thưởng cùng một lúc.",
 "Giải thích quy định email, họp trực tuyến, công cụ AI và bảo mật thông tin.",
 "So sánh thang lương, tỷ lệ luân chuyển và rủi ro trọng yếu của Vintravel với BlueOcean.",
 "Cho tôi quy định khấu trừ lương, tạm ứng lương, trả lương ngừng việc và phụ cấp đêm.",
]
for q in F: add("heavy_fanout", q, "fan-out >=3 worker; bao phủ toàn bộ khía cạnh", 3)

# G. Bổ sung ~50 câu để đạt ~150 ────────────────────────────────────────────────────────
G_cmp = [
 "So sánh số ngày phép thâm niên 3-5 năm giữa Vintravel và MeKong.",
 "Thang bảng lương cấp quản lý ở BlueOcean và MeKong khác nhau bao nhiêu?",
 "Quy trình duyệt công tác và hạn mức tạm ứng ở Vintravel so với BlueOcean.",
 "So sánh chính sách thâm niên và phép cộng thêm giữa MeKong và BlueOcean.",
 "Cơ cấu chi phí và doanh thu quý của Vintravel so với MeKong năm 2025.",
 "Tỷ lệ luân chuyển khối kinh doanh ở 3 công ty khác nhau thế nào?",
 "So sánh hạn mức phê duyệt cấp Giám đốc khối giữa Vintravel và BlueOcean.",
 "Giờ đào tạo khối sản xuất ở MeKong so với khối logistics khác bao nhiêu?",
 "So sánh nhân sự theo phòng ban giữa MeKong và BlueOcean.",
 "Xếp hạng rủi ro trọng yếu của BlueOcean và Vintravel khác nhau ở đâu?",
]
for q in G_cmp: add("compare_company", q, "fan-out theo công ty; nêu khác biệt", 2)

G_topic = [
 "Cho tôi quy định nghỉ phép, làm thêm giờ, và phụ cấp làm đêm cùng lúc.",
 "Tóm tắt chính sách thử việc, đào tạo nghề, và hợp đồng lao động.",
 "Giải thích chế độ hưu trí, bảo hiểm xã hội, và trợ cấp thôi việc.",
 "Nêu quy định kỷ luật, khiếu nại, và phòng chống quấy rối nơi làm việc.",
 "Cho tôi biết quy định bảo mật, quản lý văn bản, và tiêu hủy tài liệu.",
 "Tóm tắt: nghỉ kết hôn, nghỉ tang, nghỉ ốm, và nghỉ thai sản.",
 "Giải thích lương cơ bản, phụ cấp, thưởng, và các khoản khấu trừ.",
 "Nêu quy định an ninh ra vào, quản lý thẻ nhân viên, và sử dụng tài sản chung.",
 "Cho tôi quy trình mua sắm, sử dụng phòng họp, và quản lý quà tặng.",
 "Tóm tắt quy định email, công cụ AI, và bảo mật thông tin nội bộ.",
 "Giải thích phép năm, phép thâm niên, chuyển phép, và quy đổi phép.",
 "Nêu thời giờ làm việc, làm thêm giờ, nghỉ giữa giờ, và nghỉ hằng tuần.",
 "Cho tôi chế độ cho lao động nữ, lao động chưa thành niên, và người khuyết tật.",
 "Tóm tắt thỏa ước lao động tập thể, thương lượng tập thể, và đình công.",
 "Giải thích quy định tạm ứng lương, khấu trừ lương, và trả lương ngừng việc.",
]
for q in G_topic: add("multi_topic", q, "fan-out theo chủ đề; trả đủ mọi khía cạnh", 2)

G_hr = [
 "Tôi còn bao nhiêu phép, và chính sách nghỉ ốm có lương thế nào?",
 "Cho tôi số phép còn lại và quy định nghỉ lễ trong năm.",
 "Tôi còn mấy ngày phép, và phụ cấp làm đêm tính ra sao?",
 "Quỹ phép của tôi và quy trình tạo đơn nghỉ phép như thế nào?",
 "Tôi còn bao nhiêu phép, và nếu làm thêm giờ thì được trả thế nào?",
 "Số phép còn lại của tôi và chế độ thai sản theo công ty quy định ra sao?",
 "Tôi còn mấy ngày phép, và quy định chuyển phép chưa dùng sang năm sau?",
 "Cho tôi phép còn lại và mức khấu trừ bảo hiểm hằng tháng của tôi.",
 "Tôi còn bao nhiêu phép và chính sách thưởng cuối năm ra sao?",
 "Số phép của tôi, và nếu nghỉ việc thì cần báo trước bao lâu?",
]
for q in G_hr: add("hr_plus_policy", q, "hr_lookup + rag_retrieve — trả cả hai", 2)

G_cross = [
 "So sánh chế độ phép của VSF và Vintravel, kèm số phép còn lại của tôi.",
 "Quy định bảo mật tài liệu và quy định email nội bộ chồng lấn ở đâu?",
 "So sánh nghỉ thai sản theo luật, theo nội quy mẫu, và theo VSF.",
 "Thuế hộ kinh doanh nhóm 3 và nhóm 4 khác nhau thế nào về GTGT và TNCN?",
 "So sánh quy trình nghỉ việc của VSF và quy định báo trước trong Bộ luật.",
 "Nội quy văn phòng và nội quy kho trong tài liệu ảnh quy định gì khác nhau?",
 "So sánh quy định làm thêm giờ và nghỉ bù theo luật và nội quy công ty.",
 "Chế độ ốm đau và chế độ tai nạn lao động khác nhau ra sao?",
 "So sánh hạn mức chi tiêu MeKong và quy chế quản lý nhà cung cấp.",
 "Quy định PCCC và quy định sử dụng điện trong tài liệu ảnh khác nhau thế nào?",
]
for q in G_cross: add("cross_domain", q, "2 lĩnh vực -> 2 retrieval; nêu khác biệt", 2)

if __name__ == "__main__":
    import json, os
    from collections import Counter
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "..", "questions", "labels_multiagent.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for d in DATA:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print("TOTAL multiagent:", len(DATA), dict(Counter(d["subtype"] for d in DATA)))
    print("wrote", os.path.normpath(out))
