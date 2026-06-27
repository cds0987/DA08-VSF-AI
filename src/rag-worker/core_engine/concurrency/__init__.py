"""Concurrency primitives chung cho core_engine (elastic feeders, gates)."""

from __future__ import annotations

from core_engine.concurrency.adaptive_limiter import AdaptiveConcurrencyLimiter

__all__ = ["AdaptiveConcurrencyLimiter"]
