import sys
from pathlib import Path

# Đặt src/mcp-service lên sys.path để `import app.*` chạy được khi pytest từ đây.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
