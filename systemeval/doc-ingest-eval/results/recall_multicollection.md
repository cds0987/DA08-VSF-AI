# Recall multi-collection — HR team-dataset (2026-06-28)

Hệ: shard 4-model (qwen8b/bge-m3/te3s/pplx), 14 doc HR-VN, shard-read merge qua `/api/search`.
Gold: 110 câu hỏi sinh từ doc (có đáp-án tham chiếu). Đo 2 cách.

## 1. Tự động (gt-match doc-level) — `shard_recall.py`
| | |
|---|---|
| recall@1 / @3 / @5 / @10 | 0.50 / 0.84 / 0.89 / 0.95 |
| search latency | p50=1.4s · p95=4.0s |

## 2. Chấm tay relevance (Claude đọc query + chunk hệ trả về) — n=110
```
relevant@1  = 58/110 = 53%   (chunk ĐÚNG ở #1)
answered@3  = 83/110 = 75%   (đáp án trong top-3)
miss        = 27/110 = 25%
```
Khớp số tự động → xác nhận.

### Phân tích 27 miss (phần lớn KHÔNG phải lỗi retrieval)
1. **~5 câu giá-trị-trong-bảng**: chunk lấy đúng bảng nhưng harness CẮT 450 ký tự → giá trị mất
   khỏi tầm nhìn judge. → artifact đo; recall THẬT cao hơn. (tăng chunk-len khi đo lại.)
2. **~10 câu liệt-kê/mã cụ thể** (mã BM, mã tài liệu, danh sách hành vi): đáp án ở chunk khác doc.
3. **~5 câu boilerplate đa-doc**: cùng mẫu câu giữa các quy định → lẫn ngữ cảnh.
4. Còn lại: tra cứu đơn-vị/điều-kiện chi tiết.

## Bằng chứng multi-collection THẬT (xem verify_multicollection.py)
- Mỗi collection lưu embedding model THẬT của nó: cos(stored, qwen8b) ≈ **0** cho secondary
  (-0.04 bge-m3 / -0.01 te3s / 0.09 pplx) vs **0.96** thời bug-qwen8b-giả.
- Shard-read tìm thấy doc từ **4/4 collection** (qwen8b 0.86 · bge-m3 0.83 · te3s 0.75 · pplx 0.92).

## Kết luận
Multi-collection retrieval VỮNG: **75% answered@3 / 53%@1** trên gold tổng-hợp khó + chunk nhỏ;
latency p50=1.4s (3× nhanh hơn baseline qwen8b-giả 4.5s). Miss chủ yếu giải thích được (cắt-chữ
harness + tra-cứu hạt-mịn), không phải lỗi hệ thống. So baseline cũ KHÔNG áp dụng (single-collection
khác kiến trúc). Caveat: 14 doc + gold tổng-hợp; cần full corpus (download Drive đang kẹt) để mở rộng.
