"""Real-model backends. Only the CLI uses this; tests inject fakes."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace

from app.bootstrap.settings import settings
from app.infrastructure.ai.components import COMPONENTS, ComponentSpec
from app.infrastructure.ai.intent_classifier import complete_intent
from app.infrastructure.ai.tutor_turn_model import QwenLeakJudge, QwenTutorTurnGateway
from evals.runner import Backends
from evals.semantic import SemanticGrader


def preflight(*, check_math_executor: bool = True) -> None:
    if not settings.dashscope_api_key:
        raise SystemExit(
            "缺少 DASHSCOPE_API_KEY / VLM_API_KEY：真实模型评测需要联网和密钥。离线校验请用 `validate`。"
        )
    if check_math_executor:
        from app.agent_specs.definitions import load_definitions
        from app.application.ports.math_engine import MathInput
        from app.bootstrap.math_engine import math_engine

        tutor_unit = load_definitions().units.get("tutoring.turn")
        if tutor_unit and "tutoring.math" in tutor_unit.tools:
            probe = math_engine().execute(
                MathInput(op="equivalent", args={"left": "6*7", "right": "42"})
            )
            if probe.status != "ok" or probe.verdict != "equal":
                raise SystemExit(
                    f"tutoring.math 已启用但数学执行器预检未通过（status={probe.status}, error={probe.error_code}）；"
                    "请先启动 math-engine 服务或设置 MATH_ENGINE_MODE=subprocess。"
                )


def eval_settings() -> SimpleNamespace:
    """Bypass the runtime agent switch and env overrides: the evaluation names its own model."""
    return SimpleNamespace(
        ai_model_overrides="",
        agent_model_timeout_seconds=settings.agent_model_timeout_seconds,
        dashscope_api_key=settings.dashscope_api_key,
        agent_model_enabled=True,
    )


def build_backends(spec: ComponentSpec, *, native_only=False) -> Backends:
    runtime = eval_settings()
    if spec.component_id == "tutoring.turn":
        return Backends(
            semantic_grader=None if native_only else SemanticGrader(settings_obj=runtime),
            tutor_model=QwenTutorTurnGateway(spec=spec, settings_obj=runtime),
            backup_model=QwenTutorTurnGateway(
                spec=COMPONENTS.get("tutoring.turn-backup"), settings_obj=runtime
            ),
            leak_judge=QwenLeakJudge(
                settings_obj=runtime
            ),  # production judge, registered model
        )
    if spec.component_id == "companion.intent":
        return Backends(
            intent_complete=partial(complete_intent, spec=spec, settings_obj=runtime)
        )
    raise ValueError(f"no evaluation backend for {spec.component_id}")
