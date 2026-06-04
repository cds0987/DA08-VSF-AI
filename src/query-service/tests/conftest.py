import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AUTH_MODE", "mock")
os.environ.setdefault("LLM_MODE", "mock")
os.environ.setdefault("ENABLE_DEV_ENDPOINTS", "true")

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.infrastructure.config import get_settings  # noqa: E402
from app.interfaces.api.dependencies import reset_state_for_tests  # noqa: E402


@pytest.fixture(autouse=True)
def reset_state():
    get_settings.cache_clear()
    reset_state_for_tests()
    yield
    reset_state_for_tests()


@pytest.fixture
def tokens():
    return {
        "hr": "mock-user-hr",
        "finance": "mock-user-finance",
        "admin": "mock-admin",
    }
