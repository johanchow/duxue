"""Conservative local safety screen used until a dedicated provider is configured."""

from __future__ import annotations


class LocalSafetyScreening:
    _HIGH_RISK_PHRASES = ("不想活", "想自杀", "去死", "伤害自己", "伤害他人")

    def blocks_input(self, *, text: str) -> bool:
        return any(phrase in text for phrase in self._HIGH_RISK_PHRASES)

    def blocks_output(self, *, text: str) -> bool:
        return any(phrase in text for phrase in self._HIGH_RISK_PHRASES)
