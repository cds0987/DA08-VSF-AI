"""Import side-effect: đăng ký mọi role vào AGENT_REGISTRY. Thêm role mới = tạo file
+ @register_agent, rồi import ở đây (hoặc khai entry-point group 'vsf.query.agents')."""
from app.agents.roles import (  # noqa: F401
    analyze,
    critic,
    hr_lookup,
    rag_retrieve,
    synthesize_recommend,
)
