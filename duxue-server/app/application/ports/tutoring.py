"""Ports owned by the Tutoring application boundary."""

from __future__ import annotations

from typing import Protocol


class SafetyScreeningPort(Protocol):
    """Input and output screening is independent from the response model."""

    def blocks_input(self, *, text: str) -> bool:
        ...

    def blocks_output(self, *, text: str) -> bool:
        ...
