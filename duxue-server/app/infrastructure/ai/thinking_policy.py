"""Unified thinking_effort -> provider API parameter mapping across model families.

Abstract effort tiers used across routing and workflows:
- ``off``: thinking disabled (non-streaming JSON object mode).
- ``low``: light reasoning (primary school, routine checks, repair turns).
- ``medium``: moderate reasoning (standard multi-step tutoring, worksheet checks).
- ``high``: deep reasoning (blueprint/dossier solver for complex problems).

Provider mapping rules:
- DeepSeek family (``deepseek-*``): supports ``reasoning_effort`` (``low`` / ``high`` / ``max``),
  ignores ``thinking_budget``. Both ``low`` and ``medium`` map to DeepSeek ``low`` to avoid
  defaulting to ``high`` (4k-5k+ reasoning tokens) on interactive tutoring turns; ``high`` maps
  to DeepSeek ``high``.
- Qwen hybrid-thinking family (default): uses ``enable_thinking`` + ``thinking_budget`` capped
  by component configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ThinkingEffort = Literal["off", "low", "medium", "high"]
VALID_THINKING_EFFORTS: frozenset[str] = frozenset({"off", "low", "medium", "high"})

_EFFORT_RANK: dict[ThinkingEffort, int] = {
    "off": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}

_QWEN_EFFORT_BUDGETS: dict[ThinkingEffort, int] = {
    "low": 1024,
    "medium": 2560,
    "high": 8192,
}


@dataclass(frozen=True)
class ProviderThinkingParams:
    enable_thinking: bool
    reasoning_effort: str | None = None
    thinking_budget: int | None = None
    effective_effort: ThinkingEffort = "off"
    supports_json_object_with_thinking: bool = False


def normalize_thinking_effort(
    value: object,
    *,
    legacy_thinking: object = None,
    default: ThinkingEffort = "medium",
) -> ThinkingEffort:
    """Normalize ``thinking_effort`` with backward-compatible fallback to legacy ``thinking``."""
    if isinstance(value, str) and value in VALID_THINKING_EFFORTS:
        return value  # type: ignore[return-value]
    if legacy_thinking == "off":
        return "off"
    if legacy_thinking == "default":
        return default
    return default


def cap_thinking_effort(effort: ThinkingEffort, cap: ThinkingEffort) -> ThinkingEffort:
    """Return the lower of ``effort`` and ``cap`` (preserves ``off``)."""
    return effort if _EFFORT_RANK[effort] <= _EFFORT_RANK[cap] else cap


def is_deepseek_model(model: str | None) -> bool:
    return "deepseek" in (model or "").strip().lower()


def supports_json_object_with_thinking(model: str | None) -> bool:
    """Whether ``model`` supports ``response_format={"type": "json_object"}`` when thinking is enabled.

    Verified on DashScope OpenAI-compatible API:
    - DeepSeek family (``deepseek-*``): supports ``enable_thinking=True`` + ``reasoning_effort``
      together with ``response_format={"type": "json_object"}`` (including streaming, straight
      quotes, LaTeX, and multimodal inputs).
    - Qwen hybrid-thinking family (default): kept ``False`` to avoid historical constrained-decoding
      whitespace-gap truncation and HTTP 400 ``InternalError.Algo.InvalidParameter`` aborts.
    """
    return is_deepseek_model(model)


def _min_positive(*values: int | None) -> int | None:
    positives = [v for v in values if isinstance(v, int) and v > 0]
    return min(positives) if positives else None


def resolve_provider_thinking(
    model: str | None,
    *,
    effort: ThinkingEffort | None = None,
    enable_thinking: bool = False,
    thinking_budget: int | None = None,
    reasoning_effort: str | None = None,
) -> ProviderThinkingParams:
    """Translate abstract ``effort`` (or legacy flags) into model-family API parameters."""
    deepseek = is_deepseek_model(model)
    json_with_thinking = supports_json_object_with_thinking(model)

    if effort is not None:
        if effort == "off":
            return ProviderThinkingParams(
                enable_thinking=False,
                reasoning_effort=None,
                thinking_budget=None,
                effective_effort="off",
                supports_json_object_with_thinking=json_with_thinking,
            )
        if deepseek:
            ds_effort = "high" if effort == "high" else "low"
            return ProviderThinkingParams(
                enable_thinking=True,
                reasoning_effort=ds_effort,
                thinking_budget=None,
                effective_effort=effort,
                supports_json_object_with_thinking=json_with_thinking,
            )
        target_budget = _QWEN_EFFORT_BUDGETS[effort]
        effective_budget = (
            _min_positive(thinking_budget, target_budget)
            if effort in {"low", "medium"}
            else (thinking_budget if isinstance(thinking_budget, int) and thinking_budget > 0 else target_budget)
        )
        return ProviderThinkingParams(
            enable_thinking=True,
            reasoning_effort=None,
            thinking_budget=effective_budget,
            effective_effort=effort,
            supports_json_object_with_thinking=json_with_thinking,
        )

    # Legacy path (no explicit effort): keep enable_thinking=False as off,
    # and prevent DeepSeek from silently ignoring thinking_budget and defaulting to high.
    if not enable_thinking:
        return ProviderThinkingParams(
            enable_thinking=False,
            reasoning_effort=None,
            thinking_budget=None,
            effective_effort="off",
            supports_json_object_with_thinking=json_with_thinking,
        )

    if deepseek:
        if reasoning_effort is not None:
            inferred: ThinkingEffort = "low" if reasoning_effort == "low" else "high"
            return ProviderThinkingParams(
                enable_thinking=True,
                reasoning_effort=reasoning_effort,
                thinking_budget=None,
                effective_effort=inferred,
                supports_json_object_with_thinking=json_with_thinking,
            )
        if isinstance(thinking_budget, int) and 0 < thinking_budget <= 2560:
            return ProviderThinkingParams(
                enable_thinking=True,
                reasoning_effort="low",
                thinking_budget=None,
                effective_effort="low" if thinking_budget <= 1024 else "medium",
                supports_json_object_with_thinking=json_with_thinking,
            )
        return ProviderThinkingParams(
            enable_thinking=True,
            reasoning_effort="high",
            thinking_budget=None,
            effective_effort="high",
            supports_json_object_with_thinking=json_with_thinking,
        )

    inferred_qwen: ThinkingEffort = (
        "low"
        if isinstance(thinking_budget, int) and 0 < thinking_budget <= 1024
        else "medium"
        if isinstance(thinking_budget, int) and 0 < thinking_budget <= 2560
        else "high"
    )
    return ProviderThinkingParams(
        enable_thinking=True,
        reasoning_effort=reasoning_effort,
        thinking_budget=thinking_budget,
        effective_effort=inferred_qwen,
        supports_json_object_with_thinking=json_with_thinking,
    )
