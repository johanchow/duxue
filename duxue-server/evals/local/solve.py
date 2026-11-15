"""Evaluation-only stateless solution adapter; never a Ward workflow or policy change."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

PROMPT = Path(__file__).with_name("solve-prompt.txt").read_text()


class Solution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    solution: str = Field(min_length=1, max_length=30000)


def identity(spec):
    return {
        "execution_target": "solve",
        "model_from": "snapshot:tutoring.turn",
        "model": spec.model,
        "temperature": spec.temperature,
        "max_output_tokens": spec.max_tokens,
        "enable_thinking": bool(getattr(spec, "enable_thinking", False)),
        "thinking_budget": getattr(spec, "thinking_budget", None),
        "prompt_id": "evals.local.solve.v1",
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
    }


def complete(case, spec, images):
    if images and not spec.accepts_images:
        raise ValueError("solution model cannot receive required images")
    from app.infrastructure.ai.components import complete_json_chat

    # This adapter is deliberately not a production TutorTurnLoop invocation.
    # The model/parameters stay pinned; the explicit evaluation prompt has its own digest.
    user = [{"type": "text", "text": case.student_said}]
    user.extend({"type": "image_url", "image_url": {"url": u}} for u in images)
    completion = complete_json_chat(
        timeout=spec.timeout_seconds or 60,
        model=spec.model,
        temperature=spec.temperature,
        max_tokens=spec.max_tokens,
        messages=[
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": user},
        ],
        enable_thinking=bool(getattr(spec, "enable_thinking", False)),
        thinking_budget=getattr(spec, "thinking_budget", None),
    )
    if completion.finish_reason == "length":
        raise ValueError("solution output truncated")
    return Solution.model_validate(json.loads(completion.raw)).solution
