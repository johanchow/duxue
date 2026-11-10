"""Composition root for the optional, isolated math adapter."""

import os

from app.infrastructure.math_engine.adapter import MathEngineAdapter


def math_engine():
    return MathEngineAdapter(
        os.environ.get("MATH_ENGINE_SOCKET", "/run/math/engine.sock")
    )


def tutoring_workflow(db):
    from app.application.workflows.tutoring_workflow import TutoringWorkflow

    return TutoringWorkflow(db, math_engine=math_engine())
