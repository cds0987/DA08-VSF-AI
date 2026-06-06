from __future__ import annotations

from pathlib import Path

import pytest

from core_engine.config_loader import load_config


def test_load_config_interpolates_and_validates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CAPTION_MAX_CHARS", "5000")
    path = tmp_path / "config.yaml"
    path.write_text(
        """
active: baseline
profiles:
  baseline:
    common: { ai_mode: offline }
    embedder: { model: text-embedding-3-small, dimension: 256 }
    captioner: { impl: none, model: gpt-4o-mini, params: { max_chars: "${CAPTION_MAX_CHARS}" } }
    parser: { impl: local, params: { max_workers: 2 } }
    chunker:
      impl: heading_sections
      params: { parent_max_words: 220, child_max_words: 90, child_overlap_words: 15 }
    vector_store:
      impl: qdrant
      params: { collection: rag_chatbot, url: "", api_key: "" }
""",
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.captioner.params["max_chars"] == "5000"


def test_load_config_resolves_extends(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
active: child
profiles:
  baseline:
    common: { ai_mode: offline }
    embedder: { model: text-embedding-3-small, dimension: 256 }
    captioner: { impl: provider, model: gpt-4o-mini, params: { max_chars: 6000 } }
    parser: { impl: local, params: { max_workers: 2 } }
    chunker:
      impl: heading_sections
      params: { parent_max_words: 220, child_max_words: 90, child_overlap_words: 15 }
    vector_store:
      impl: qdrant
      params: { collection: rag_chatbot, url: "", api_key: "" }
  child:
    extends: baseline
    captioner: { params: { max_chars: 5000 } }
""",
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.captioner.impl == "provider"
    assert cfg.captioner.params["max_chars"] == 5000


def test_load_config_rejects_missing_required_env(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
common: { ai_mode: offline }
embedder: { model: text-embedding-3-small, dimension: "${MISSING_ENV}" }
captioner: { impl: none, model: gpt-4o-mini, params: {} }
parser: { impl: local, params: { max_workers: 2 } }
chunker:
  impl: heading_sections
  params: { parent_max_words: 220, child_max_words: 90, child_overlap_words: 15 }
vector_store:
  impl: qdrant
  params: { collection: rag_chatbot, url: "", api_key: "" }
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Missing required environment variable"):
        load_config(path)


def test_load_config_rejects_nested_embed_block(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
common: { ai_mode: offline }
embedder: { model: text-embedding-3-small, dimension: 256 }
captioner:
  impl: provider
  model: gpt-4o-mini
  embed: { model: rogue }
  params: {}
parser: { impl: local, params: { max_workers: 2 } }
chunker:
  impl: heading_sections
  params: { parent_max_words: 220, child_max_words: 90, child_overlap_words: 15 }
vector_store:
  impl: qdrant
  params: { collection: rag_chatbot, url: "", api_key: "" }
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Embed config must live in top-level embedder block"):
        load_config(path)


def test_load_config_keeps_inline_placeholders_literal(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
common: { ai_mode: offline }
embedder: { model: text-embedding-3-small, dimension: 256 }
captioner: { impl: none, model: gpt-4o-mini, params: {} }
parser: { impl: local, params: { max_workers: 2 } }
chunker:
  impl: heading_sections
  params: { parent_max_words: 220, child_max_words: 90, child_overlap_words: 15 }
vector_store:
  impl: qdrant
  params: { collection: rag_chatbot, url: "http://${HOST}:6333", api_key: "" }
""",
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.vector_store.params["url"] == "http://${HOST}:6333"


def test_load_config_ignores_required_env_in_inactive_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Một `${VAR}` bắt buộc (không default) ở profile KHÔNG active không được làm vỡ
    # việc load profile đang active.
    monkeypatch.delenv("VECTOR_DB_URL", raising=False)
    monkeypatch.setenv("PIPELINE_PROFILE", "baseline")
    path = tmp_path / "config.yaml"
    path.write_text(
        """
active: baseline
profiles:
  baseline:
    common: { ai_mode: offline }
    embedder: { model: text-embedding-3-small, dimension: 256 }
    captioner: { impl: none, model: gpt-4o-mini, params: {} }
    parser: { impl: local, params: { max_workers: 2 } }
    chunker:
      impl: heading_sections
      params: { parent_max_words: 220, child_max_words: 90, child_overlap_words: 15 }
    vector_store:
      impl: qdrant
      params: { collection: rag_chatbot, url: "", api_key: "" }
  prod:
    extends: baseline
    vector_store:
      impl: qdrant
      params:
        collection: rag_chatbot
        url: ${VECTOR_DB_URL}
""",
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.vector_store.params["url"] == ""
