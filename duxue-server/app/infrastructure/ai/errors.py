"""Stable, provider-neutral model failure vocabulary shared by the AI layer."""

from __future__ import annotations


class ModelTimeBudgetExceeded(TimeoutError):
    """All model calls in the current turn have exhausted their shared deadline."""


class ModelGatewayError(RuntimeError):
    """A provider or candidate validation failure safe for deterministic fallback."""
