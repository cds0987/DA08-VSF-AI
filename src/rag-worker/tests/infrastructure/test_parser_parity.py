from __future__ import annotations

import ast
from pathlib import Path

from app.infrastructure.external.local_parser import _DEFAULT_READER_IMPL


def _load_document_service_allowed_extensions() -> set[str]:
    repo_root = Path(__file__).resolve().parents[4]
    common_path = repo_root / "src" / "document-service" / "app" / "application" / "use_cases" / "documents" / "common.py"
    module = ast.parse(common_path.read_text(encoding="utf-8"), filename=str(common_path))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "ALLOWED_EXTENSIONS":
                return set(ast.literal_eval(node.value))
    raise AssertionError(f"cannot find ALLOWED_EXTENSIONS in {common_path}")


def test_all_document_service_extensions_have_reader() -> None:
    allowed_extensions = _load_document_service_allowed_extensions()
    missing = allowed_extensions - set(_DEFAULT_READER_IMPL)
    assert not missing, (
        f"Extensions allowed by document-service but missing reader in rag-worker: {sorted(missing)}. "
        "Add a reader in local_parser or remove the extension from ALLOWED_EXTENSIONS."
    )
