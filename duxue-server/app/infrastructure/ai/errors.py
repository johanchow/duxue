"""Stable, provider-neutral model failure vocabulary shared by the AI layer."""

from __future__ import annotations


class ModelGatewayError(RuntimeError):
    """A provider or candidate validation failure safe for deterministic fallback."""
