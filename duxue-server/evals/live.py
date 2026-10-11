"""Real-model backends. Only the CLI uses this; tests inject fakes."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace

from app.bootstrap.settings import settings
from app.infrastructure.ai.components import ComponentSpec
from app.infrastructure.ai.intent_classifier import complete_intent
from app.infrastructure.ai.tutor_turn_model import QwenLeakJudge, QwenTutorTurnGateway
from evals.runner import Backends


def preflight() -> None:
    if not settings.dashscope_api_key:
        raise SystemExit("缺少 DASHSCOPE_API_KEY / VLM_API_KEY：真实模型评测需要联网和密钥。离线校验请用 `validate`。")


def eval_settings() -> SimpleNamespace:
    """Bypass the runtime agent switch and env overrides: the evaluation names its own model."""
    return SimpleNamespace(
        ai_model_overrides="", agent_model_timeout_seconds=settings.agent_model_timeout_seconds,
        dashscope_api_key=settings.dashscope_api_key, agent_model_enabled=True,
    )


def build_backends(spec: ComponentSpec) -> Backends:
    runtime = eval_settings()
    if spec.component_id == "tutoring.turn":
        return Backends(
            tutor_model=QwenTutorTurnGateway(spec=spec, settings_obj=runtime),
            leak_judge=QwenLeakJudge(settings_obj=runtime),  # production judge, registered model
        )
    if spec.component_id == "companion.intent":
        return Backends(intent_complete=partial(complete_intent, spec=spec, settings_obj=runtime))
    raise ValueError(f"no evaluation backend for {spec.component_id}")
