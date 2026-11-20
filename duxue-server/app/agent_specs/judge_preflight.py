"""Pre-publish contract probes for tutoring Judges (text protection + math consistency).

Catches prompt/schema drift (such as R12 omitting `math_consistent`) before a
draft is published, preventing wasted double-retries and production fallbacks.
"""

from __future__ import annotations

import json

from app.agent_specs.admin_bundle import CompiledBundle
from app.agent_specs.definitions import use_definitions
from app.application.workflows.tutor_turn import LeakJudgePort

_TEXT_SAMPLE_PROBLEM = json.dumps(
    {
        "current_request": "解方程 x + 3 = 7，第一步怎么做？",
        "recent_problems": ["解方程 x + 3 = 7"],
        "student_evidence": [],
    },
    ensure_ascii=False,
)
_TEXT_SAMPLE_REPLY = "先把方程左边的 +3 移到右边想一想，右边会变成什么算式？"

_MATH_SAMPLE_CONTEXT = {
    "problem": json.dumps(
        {
            "current_request": "90 - 37 = 53 对吗？",
            "recent_problems": ["计算 90 - 37"],
            "student_evidence": ["90 - 37 = 53"],
        },
        ensure_ascii=False,
    ),
    "candidate_turn": {
        "type": "work",
        "relation": "same",
        "depth": "reasoning",
        "student_move": "submit_answer",
    },
    "math_records": [
        {
            "request_id": "preflight_eq_1",
            "op": "equivalent",
            "args": {"left": "90-37", "right": "53"},
            "status": "ok",
            "verdict": "equal",
            "value": True,
        }
    ],
    "math_claims": [
        {"request_id": "preflight_eq_1", "step_ref": "1", "assertion": "equal"}
    ],
}
_MATH_SAMPLE_REPLY = "90 - 37 确实等于 53，这一步算对了！"


def probe_judge_contracts(
    compiled: CompiledBundle,
    *,
    judge: LeakJudgePort | None = None,
) -> list[str]:
    """Probe text-protection and (when math tool enabled) math-consistency Judge outputs.

    Returns a list of error strings; empty list means all required outputs are valid.
    """
    errors: list[str] = []
    with use_definitions(compiled.catalog):
        active_judge = judge
        if active_judge is None:
            from app.infrastructure.ai.tutor_turn_model import QwenLeakJudge

            active_judge = QwenLeakJudge()

        # 1. Text protection probe: must return structured verdict with boolean leaks & answer_protected
        try:
            text_res = active_judge.leaks(
                text=_TEXT_SAMPLE_REPLY,
                task_title="数学作业",
                problem_summary=_TEXT_SAMPLE_PROBLEM,
                images=None,
            )
        except Exception as exc:  # noqa: BLE001
            text_res = None
            errors.append(f"text_leak probe error: {exc}")
        else:
            if not isinstance(text_res, dict) or type(text_res.get("leaks")) is not bool:
                errors.append("text_leak probe failed: missing boolean 'leaks' verdict")
            elif type(text_res.get("answer_protected")) is not bool:
                errors.append("text_leak probe failed: missing boolean 'answer_protected'")

        # 2. Math consistency probe (when tutoring.math is enabled on tutoring.turn)
        turn_tools = compiled.catalog.units["tutoring.turn"].tools
        if "tutoring.math" in turn_tools:
            check_math = getattr(active_judge, "check_math", None)
            if check_math is None:
                errors.append("math_consistency probe failed: judge does not implement check_math")
            else:
                try:
                    math_res = check_math(
                        text=_MATH_SAMPLE_REPLY,
                        context=_MATH_SAMPLE_CONTEXT,
                        images=[],
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"math_consistency probe error: {exc}")
                else:
                    if type(math_res) is not bool:
                        errors.append(
                            "math_consistency probe failed: missing boolean 'math_consistent' output"
                        )
    return errors
