"""_prep_body: chuyển field 'reasoning' (cắt độ nghĩ) -> extra_body cho OpenRouter, bỏ cho OpenAI.

_prep_body KHÔNG dùng self -> gọi unbound (self=None) để test thuần, không dựng Router đầy đủ.
"""
from ai_router.router import Router
from ai_router.schemas import Provider, RouteDecision


def _dec(provider: Provider) -> RouteDecision:
    return RouteDecision(
        key_id="k", provider=provider, api_key="x", base_url=None,
        model_name="m", model_id="m", tier="paid",
    )


def test_prep_body_forwards_reasoning_to_extra_body_for_openrouter():
    body = {"model": "plan", "messages": [], "reasoning": {"effort": "low"}}
    out = Router._prep_body(None, body, _dec(Provider.OPENROUTER))
    assert "reasoning" not in out, "reasoning KHÔNG được để top-level (create từ chối kwarg lạ)"
    assert out["extra_body"]["reasoning"] == {"effort": "low"}


def test_prep_body_drops_reasoning_for_openai_savemode():
    # save_mode degrade -> gpt-4o-mini (OpenAI) KHÔNG hiểu 'reasoning' -> phải bỏ (tránh 400).
    body = {"model": "plan", "messages": [], "reasoning": {"effort": "low"}}
    out = Router._prep_body(None, body, _dec(Provider.OPENAI))
    assert "reasoning" not in out
    assert "reasoning" not in (out.get("extra_body") or {})


def test_prep_body_no_reasoning_passthrough_unchanged():
    body = {"model": "plan", "messages": []}
    out = Router._prep_body(None, body, _dec(Provider.OPENROUTER))
    assert "extra_body" not in out


# ───── OCR //hóa: ai-router TỰ inject reasoning-off server-side (rag-worker KHÔNG gửi) ─────

def test_prep_body_ocr_injects_reasoning_off_for_openrouter():
    # capability=ocr + OpenRouter (qwen-vl) -> reasoning:{enabled:false} (tắt nghĩ -> nhanh + 100% acc)
    body = {"model": "ocr", "messages": []}
    out = Router._prep_body(None, body, _dec(Provider.OPENROUTER), "ocr")
    assert out["extra_body"]["reasoning"] == {"enabled": False}
    assert "reasoning" not in out  # KHÔNG top-level


def test_prep_body_ocr_no_reasoning_for_openai_degrade():
    # ocr degrade OpenAI (e2e không có OpenRouter key) -> KHÔNG inject -> tránh 400 'Unrecognized reasoning'
    body = {"model": "ocr", "messages": [], "max_tokens": 2000}
    out = Router._prep_body(None, body, _dec(Provider.OPENAI), "ocr")
    assert "reasoning" not in out
    assert "reasoning" not in (out.get("extra_body") or {})
    assert out["max_completion_tokens"] == 2000  # OpenAI vẫn convert max_tokens


def test_prep_body_strips_nested_extra_body_reasoning_for_openai():
    # An toàn 2 lớp: client lỡ nhét reasoning NESTED trong extra_body + provider OpenAI -> phải gỡ
    body = {"model": "ocr", "messages": [], "extra_body": {"reasoning": {"enabled": False}}}
    out = Router._prep_body(None, body, _dec(Provider.OPENAI), "ocr")
    assert "reasoning" not in (out.get("extra_body") or {})


def test_prep_body_non_ocr_no_auto_inject():
    # capability khác ocr -> KHÔNG auto-inject reasoning
    body = {"model": "answer", "messages": []}
    out = Router._prep_body(None, body, _dec(Provider.OPENROUTER), "answer")
    assert "extra_body" not in out
