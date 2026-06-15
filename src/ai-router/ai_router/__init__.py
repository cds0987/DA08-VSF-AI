"""AI Router — gateway tương thích OpenAI, stateless, đa pool key.

Xem PLAN.md ở thư mục cha. Service AI-logic chỉ khai Ý ĐỊNH (capability + inputs);
router chọn (api_key, base_url, model_name) tối ưu chi phí + phân bố tải, rồi gọi.
"""

__version__ = "0.1.0"
