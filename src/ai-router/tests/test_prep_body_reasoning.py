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
