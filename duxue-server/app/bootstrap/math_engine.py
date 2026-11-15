"""Composition root for the optional, isolated math adapter."""

import os

from app.infrastructure.math_engine.adapter import (
    MathEngineAdapter,
    SubprocessMathEngineAdapter,
)


def math_engine():
    mode = os.environ.get("MATH_ENGINE_MODE", "socket").strip().lower()
    if os.environ.get("APP_ENV") in {"production", "prod"} and mode != "socket":
        raise ValueError("production requires MATH_ENGINE_MODE=socket")
    if mode == "subprocess":
        return SubprocessMathEngineAdapter()
    if mode != "socket":
        raise ValueError("MATH_ENGINE_MODE must be 'socket' or 'subprocess'")
    return MathEngineAdapter(
        os.environ.get("MATH_ENGINE_SOCKET", "/run/math/engine.sock")
    )


def tutoring_workflow(db):
    from app.application.workflows.tutoring_workflow import TutoringWorkflow

    return TutoringWorkflow(db, math_engine=math_engine())
