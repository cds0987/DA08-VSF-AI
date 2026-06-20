"""Import mọi adapter để chúng tự đăng ký vào registry (side-effect @register).

Thêm adapter mới: tạo file + @register, rồi import ở đây.
"""
from . import standard  # noqa: F401  (đăng ký "standard")

# Phase 1 thêm: reasoning_oai, reasoning_or
try:  # import mềm — Phase 1 mới tạo các file này
    from . import reasoning_oai  # noqa: F401
except ImportError:  # pragma: no cover
    pass
try:
    from . import reasoning_or  # noqa: F401
except ImportError:  # pragma: no cover
    pass
try:
    from . import openrouter_effort  # noqa: F401  (cắt độ nghĩ reasoning model per-node)
except ImportError:  # pragma: no cover
    pass
