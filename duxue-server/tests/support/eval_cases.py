"""Explicit v2 fixtures for replay tests; fake scoring never examines semantic text."""

from evals.grading import Grading
from evals.migrate import structural
from evals.schema import EvalCase
from evals.runner import Backends as RealBackends


class FixedScorer:
    def __init__(self, *, score=5, verdict="pass"):
        self.score = score
        self.verdict = verdict
        self.calls = []

    def metadata(self):
        return {"judge_model": "test-fake", "judge_prompt_digest": "fake-v1"}

    def grade(self, rule, **kwargs):
        self.calls.append((rule, kwargs))
        return {
            ("score" if rule.type == "score" else "verdict"): self.score
            if rule.type == "score"
            else self.verdict,
            "explanation": "Scripted test verdict, not semantic evaluation",
            "evidence": ["test-fixture"],
        }


def Backends(**kwargs):
    kwargs.setdefault("semantic_grader", FixedScorer())
    return RealBackends(**kwargs)


def grading(expect=None, component="tutoring.turn"):
    expected = expect or {}
    if component == "companion.intent" and any(
        expected.get(k) for k in ("outcome_in", "visual", "visual_kind_in")
    ):
        raise ValueError("intent cases cannot assert tutoring fields")
    if component == "tutoring.turn" and expected.get("intent_in"):
        raise ValueError("intent_in belongs to intent")
    rules = structural(
        expected
        if expected
        else ({"intent_in": ["tutoring"]} if component == "companion.intent" else {}),
        component,
    )
    return Grading.model_validate(
        {
            "deterministic": rules,
            "model_graded": []
            if component != "tutoring.turn"
            else [
                {
                    "id": "quality",
                    "type": "score",
                    "rubric_ref": "teaching-quality.v1",
                    "min_score": 4,
                }
            ],
            "reference_response": (expected.get("response") or {}).get("message"),
        }
    )


def make_case(raw):
    raw = dict(raw)
    if "grading" not in raw:
        raw["grading"] = grading(raw.pop("expect", None), raw["component"])
    return EvalCase.model_validate(raw)


def record_for_case(case):
    from evals.dialogue import TurnRecord, VERSION

    messages = [
        {
            "id": f"m{i + 1}",
            "role": "user" if m.author == "ward" else "assistant",
            "content": m.text,
            "images": m.images,
            "image_target_refs": m.image_target_refs,
        }
        for i, m in enumerate(case.history)
    ]
    messages.append(
        {
            "id": f"m{len(messages) + 1}",
            "role": "user",
            "content": case.student_said,
            "images": case.images,
        }
    )
    return TurnRecord.model_validate(
        {
            "schema_version": VERSION,
            "id": case.id,
            "type": "single_turn",
            "replay_mode": "fixed_history",
            "source": {
                "kind": case.source,
                "coverage": "authored"
                if case.source == "synthetic"
                else "observed_window",
            },
            "conversation_id": case.conversation_id,
            "turn_index": case.turn_index,
            "messages": messages,
            "checks": [
                {
                    "id": "check-1",
                    "after_message": messages[-1]["id"],
                    "component": case.component,
                    "input_snapshot": {
                        "origin": case.snapshot_origin,
                        "context": case.context.model_dump(),
                    },
                    "grading": case.grading.model_dump(by_alias=True),
                }
            ],
        }
    ).model_dump(mode="json", by_alias=True)
