"""
Guardrail services backed by llm-guard.

Two classes are provided:

  NoOpInputGuardrail / NoOpOutputGuardrail
      Used when GUARDRAILS_MODE=off (default).  Zero overhead, zero imports.

  LlmGuardInputGuardrail
      Scans user input for prompt-injection.  Returns (blocked, reason).

  LlmGuardOutputGuardrail
      Redacts PII (email, phone, …) from the LLM answer before it reaches the user.

Both real classes lazy-import llm-guard so the package only needs to be present when
the mode is active.  Tests run with mode=off and never load the heavy scanners.
"""
from __future__ import annotations


class NoOpInputGuardrail:
    async def scan(self, text: str) -> tuple[bool, str]:
        """Returns (blocked=False, reason='') — all input allowed."""
        return False, ""


class NoOpOutputGuardrail:
    async def redact(self, text: str) -> str:
        """Returns text unchanged."""
        return text


class LlmGuardInputGuardrail:
    """Blocks prompt-injection attempts using llm-guard's PromptInjection scanner."""

    def __init__(self) -> None:
        self._scanner = None

    def _get_scanner(self):
        if self._scanner is None:
            try:
                from llm_guard.input_scanners import PromptInjection  # type: ignore[import]
                from llm_guard.input_scanners.prompt_injection import MatchType  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError(
                    "llm-guard is required when GUARDRAILS_MODE=llm_guard"
                ) from exc
            self._scanner = PromptInjection(match_type=MatchType.FULL)
        return self._scanner

    async def scan(self, text: str) -> tuple[bool, str]:
        """
        Returns (blocked, reason).  blocked=True means the input was flagged.
        """
        try:
            from llm_guard import scan_prompt  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "llm-guard is required when GUARDRAILS_MODE=llm_guard"
            ) from exc
        scanner = self._get_scanner()
        sanitized, results, is_valid_list = scan_prompt(text, scanners=[scanner])
        # scan_prompt returns is_valid per scanner; False means the scanner flagged it.
        blocked = not all(is_valid_list.values()) if isinstance(is_valid_list, dict) else not all(is_valid_list)
        reason = "prompt_injection_detected" if blocked else ""
        return blocked, reason


class LlmGuardOutputGuardrail:
    """Redacts PII from LLM output using llm-guard's Anonymize scanner."""

    def __init__(self) -> None:
        self._scanner = None

    def _get_scanner(self):
        if self._scanner is None:
            try:
                from llm_guard.output_scanners import Anonymize  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError(
                    "llm-guard is required when GUARDRAILS_MODE=llm_guard"
                ) from exc
            self._scanner = Anonymize()
        return self._scanner

    async def redact(self, text: str) -> str:
        try:
            from llm_guard import scan_output  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "llm-guard is required when GUARDRAILS_MODE=llm_guard"
            ) from exc
        scanner = self._get_scanner()
        sanitized, _, _ = scan_output("", text, scanners=[scanner])
        return sanitized


def build_guardrails(settings) -> tuple:
    """
    Factory returning (InputGuardrail, OutputGuardrail) based on GUARDRAILS_MODE.

    Returns no-op objects when mode is 'off' so the pipeline works without llm-guard
    installed (dev/test).
    """
    mode = settings.guardrails_mode.strip().lower()
    if mode == "llm_guard":
        return LlmGuardInputGuardrail(), LlmGuardOutputGuardrail()
    return NoOpInputGuardrail(), NoOpOutputGuardrail()
