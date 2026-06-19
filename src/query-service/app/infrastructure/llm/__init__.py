"""MOSA LLM layer — mỗi node của LangGraph dùng 1 adapter riêng (chiến lược cắm-tháo).

Thiết kế theo đúng tinh thần MOSA của hệ thống (như routing.yaml của ai-router và
config.yaml của monitor_decision): hành vi đặc thù từng HỌ model đóng kín trong 1 adapter,
ánh xạ node -> adapter khai báo bằng manifest `profiles.yaml` (hot-config, không sửa code).

- base.py:      interface NodeLLMAdapter
- registry.py:  @register("name") + get_adapter("name")
- adapters/:    các adapter cụ thể (standard, reasoning_oai, reasoning_or)
- profiles.yaml: manifest node -> {adapter, capability, models, reasoning_effort}
- loader.py:    đọc manifest -> NodeProfile + dựng chat model cho từng node
"""
