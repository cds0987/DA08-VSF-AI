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
    async def verify_contract(self):
        return None


class FailingService:
    async def verify_contract(self):
        raise VectorstoreContractError("collection missing")


def test_main_runs_streamable_http_after_contract_verify(monkeypatch) -> None:
    mcp = StubMCP()
    monkeypatch.setattr(main_module, "load_settings", lambda: StubSettings())
    monkeypatch.setattr(main_module, "build_mcp", lambda settings: (mcp, SuccessfulService()))

    exit_code = main_module.main()

    assert exit_code == 0
    assert mcp.transport == "streamable-http"


def test_main_fails_closed_when_contract_verify_fails(monkeypatch) -> None:
    mcp = StubMCP()
    monkeypatch.setattr(main_module, "load_settings", lambda: StubSettings())
    monkeypatch.setattr(main_module, "build_mcp", lambda settings: (mcp, FailingService()))

    exit_code = main_module.main()

    assert exit_code == 1
    assert mcp.transport is None
