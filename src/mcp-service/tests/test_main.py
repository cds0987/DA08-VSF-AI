from __future__ import annotations

from dataclasses import dataclass

from app.core.contract import VectorstoreContractError
from app import main as main_module


@dataclass
class StubContract:
    index_id: str = "rag_chatbot__offline__d256"
    fingerprint: str = "88048119fce054e3"


class StubSettings:
    deployment = "in_process"

    def contract(self) -> StubContract:
        return StubContract()


class StubMCP:
    def __init__(self) -> None:
        self.transport: str | None = None

    def run(self, *, transport: str) -> None:
        self.transport = transport


class SuccessfulService:
    def __init__(self) -> None:
        self.verify_calls = 0
        self.close_calls = 0

    async def verify_contract(self):
        self.verify_calls += 1
        return None

    async def aclose(self):
        self.close_calls += 1


class FailingService:
    def __init__(self) -> None:
        self.verify_calls = 0
        self.close_calls = 0

    async def verify_contract(self):
        self.verify_calls += 1
        raise VectorstoreContractError("collection missing")

    async def aclose(self):
        self.close_calls += 1


def test_main_runs_streamable_http_after_contract_verify(monkeypatch) -> None:
    mcp = StubMCP()
    service = SuccessfulService()
    monkeypatch.setattr(main_module, "load_settings", lambda: StubSettings())
    monkeypatch.setattr(main_module, "build_mcp", lambda settings: (mcp, service))

    exit_code = main_module.main()

    assert exit_code == 0
    assert mcp.transport == "streamable-http"
    assert service.verify_calls == 1
    assert service.close_calls == 2


def test_main_fails_closed_when_contract_verify_fails(monkeypatch) -> None:
    mcp = StubMCP()
    service = FailingService()
    monkeypatch.setattr(main_module, "load_settings", lambda: StubSettings())
    monkeypatch.setattr(main_module, "build_mcp", lambda settings: (mcp, service))

    exit_code = main_module.main()

    assert exit_code == 1
    assert mcp.transport is None
    assert service.verify_calls == 1
    assert service.close_calls == 1
