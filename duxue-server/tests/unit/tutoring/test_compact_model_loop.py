"""Unit tests for the streamlined 3-action `tutoring.model_loop` (`primary -> repair -> finish`)."""

import json
from pathlib import Path

import pytest

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.definitions import use_definitions
from app.agent_specs.execution_trace import Recorder
from app.agent_specs.registrations import LEGACY_LOOP, MODEL_LOOP
from app.agent_specs.subworkflows import compact_model_loop_workflow
from app.agent_specs.subworkflows import upgrade_files as upgrade_subworkflows
from app.application.workflows.tutor_loop import run_tutor_turn
from app.application.workflows.tutor_tools import TutorToolbox
from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit
from tests.support.fakes import tutor_raw
from tests.unit.tutoring.test_tutor_visual import SEGMENT


@pytest.fixture(scope="module")
def compact_catalog():
    from scripts.upgrade_math_bundle import upgrade as add_blueprint

    source = json.loads(Path("tests/fixtures/admin-release.json").read_text())
    record = add_blueprint(source, gaokao=True)
    bundle = record["bundle"]
    files = bundle["files"]
    upgrade_subworkflows(files)
    loop_key = f"workflows/{MODEL_LOOP}.json" if f"workflows/{MODEL_LOOP}.json" in files else f"workflows/{LEGACY_LOOP}.json"
    loop_id = MODEL_LOOP if loop_key.endswith(f"{MODEL_LOOP}.json") else LEGACY_LOOP
    files[loop_key] = compact_model_loop_workflow(loop_id)
    bundle["compatibility"] = contract_compatibility(files)
    return compile_bundle(bundle).catalog


def _tools(db):
    return TutorToolbox(
        db,
        tutoring_session_id=None,
        problem=None,
        task_title=None,
        task_active=False,
        window=[],
    )


def test_compact_loop_accepts_primary_directly_without_repair(compact_catalog, db):
    class GoodModel:
        def __init__(self):
            self.calls = 0

        def complete(self, **kwargs):
            self.calls += 1
            return tutor_raw(act="guide", relation="new", content="我们先列出已知条件，你觉得第一步应该写什么？")

    class PassJudge:
        def leaks(self, **kwargs):
            return {"leaks": False, "reason": "none", "answer_protected": True}

        def check_math(self, **kwargs):
            return True

    model = GoodModel()
    trace = Recorder()
    with use_definitions(compact_catalog), trace.capture():
        res = run_tutor_turn(
            model,
            envelope={},
            instruction="引导解题",
            window=[],
            images=[],
            tools=_tools(db),
            permit=TutorPermit(answer_protected=True, attempt_summary=AttemptSummary()),
            leak_judge=PassJudge(),
            task_title=None,
            problem_summary="求 x",
        )
    assert model.calls == 1
    assert res.vetting is not None and res.vetting.failure is None
    actions = [e["node_id"].split(".")[-1] for e in trace.events if e["kind"] == "action" and e["node_id"].split(".")[-1] in {"primary", "repair", "finish"}]
    assert actions == ["primary", "finish"]


def test_compact_loop_merges_text_and_missing_visual_feedback_in_single_repair(compact_catalog, db):
    class CompoundFailModel:
        def __init__(self):
            self.repair_errors: list[str | None] = []

        def complete(self, *, repair_error=None, **kwargs):
            self.repair_errors.append(repair_error)
            if len(self.repair_errors) == 1:
                # Both leaks answer AND omits requested visual!
                return {
                    "act": "guide",
                    "content": "答案就是 x = 5！我口头给你讲一下图形。",
                    "turn": {
                        "type": "work",
                        "relation": "new",
                        "depth": "reasoning",
                        "student_move": "request_hint",
                        "next_subgoal": "画线段图",
                    },
                }
            # Repair turn fixes leak AND attaches a valid visual
            return {
                "act": "guide",
                "content": "我们先看下面的线段图，试着标出两段之间的关系。",
                "visual": SEGMENT,
                "turn": {
                    "type": "work",
                    "relation": "new",
                    "depth": "reasoning",
                    "student_move": "request_hint",
                    "next_subgoal": "标出两段长度",
                },
            }

    class TwoTurnJudge:
        def __init__(self):
            self.calls = 0

        def leaks(self, **kwargs):
            self.calls += 1
            return {"leaks": self.calls == 1, "reason": "direct_answer" if self.calls == 1 else "none", "answer_protected": True}

        def visual_leaks(self, **kwargs):
            return False

        def check_math(self, **kwargs):
            return True

    model = CompoundFailModel()
    trace = Recorder()
    with use_definitions(compact_catalog), trace.capture():
        res = run_tutor_turn(
            model,
            envelope={},
            instruction="请画个图帮我理解这道题",
            window=[],
            images=[],
            tools=_tools(db),
            permit=TutorPermit(answer_protected=True, attempt_summary=AttemptSummary()),
            leak_judge=TwoTurnJudge(),
            task_title=None,
            problem_summary="请画个图帮我理解",
        )
    assert len(model.repair_errors) == 2
    assert model.repair_errors[1] is not None
    # Compound failure merged BOTH text leak feedback AND missing visual feedback!
    assert "答案" in model.repair_errors[1] or "泄露" in model.repair_errors[1] or "direct_answer" in model.repair_errors[1]
    assert "图" in model.repair_errors[1] or "visual" in model.repair_errors[1].lower()
    assert res.vetting is not None and res.vetting.failure is None
    assert res.vetting.visual is not None
    actions = [e["node_id"].split(".")[-1] for e in trace.events if e["kind"] == "action" and e["node_id"].split(".")[-1] in {"primary", "repair", "finish"}]
    assert actions == ["primary", "repair", "finish"]


def test_compact_loop_skips_repair_on_math_check_failed_outage(compact_catalog, db):
    """Non-self-healable executor outage (`math_check_failed`) must NOT blindly retry the same model."""
    from app.infrastructure.math_engine.adapter import SubprocessMathEngineAdapter

    class MathModel:
        def __init__(self):
            self.calls = 0

        def complete(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"tool": "math", "args": {"op": "evaluate", "args": {"expression": "2 + 3"}}}
            return tutor_raw(act="guide", relation="new", content="我们先算一下 $2 + 3 = 5$，下一步怎么列式？")

    class OutageJudge:
        supports_joint_math_review = True

        def leaks(self, **kwargs):
            return {"leaks": False, "reason": "none", "answer_protected": True, "math_consistent": None}

        def check_math(self, **kwargs):
            return None  # Executor unavailable -> math_check_failed

    model = MathModel()
    tools = TutorToolbox(
        db,
        tutoring_session_id=None,
        problem=None,
        task_title=None,
        task_active=False,
        window=[],
        math_engine=SubprocessMathEngineAdapter(),
    )
    trace = Recorder()
    with use_definitions(compact_catalog), trace.capture():
        res = run_tutor_turn(
            model,
            envelope={},
            instruction="帮我看看这步",
            window=[],
            images=[],
            tools=tools,
            permit=TutorPermit(answer_protected=True, attempt_summary=AttemptSummary()),
            leak_judge=OutageJudge(),
            task_title=None,
            problem_summary=json.dumps({"current_request": "算式检查"}, ensure_ascii=False),
        )
    # 1 tool call + 1 final candidate = 2 complete calls; NO repair turn!
    assert model.calls == 2
    assert res.vetting is not None and res.vetting.failure == "math_check_failed"
    actions = [e["node_id"].split(".")[-1] for e in trace.events if e["kind"] == "action" and e["node_id"].split(".")[-1] in {"primary", "repair", "finish"}]
    assert actions == ["primary", "finish"]


def test_compact_loop_visual_only_repair_locks_approved_text(compact_catalog, db):
    """When only visual leaked, repair must lock approved act/content/turn and reuse text vetting."""
    approved_content = "我们先看看两段数量的关系，你能说出谁多谁少吗？"

    class VisualFixModel:
        def __init__(self):
            self.calls = 0

        def complete(self, **kwargs):
            self.calls += 1
            return {
                "act": "guide",
                "content": approved_content,
                "visual": SEGMENT,
                "turn": {
                    "type": "work",
                    "relation": "new",
                    "depth": "reasoning",
                    "student_move": "request_hint",
                    "next_subgoal": "比较两段长度",
                },
            }

    class VisualLeakOnceJudge:
        def __init__(self):
            self.text_calls = 0
            self.visual_calls = 0

        def leaks(self, **kwargs):
            self.text_calls += 1
            return {"leaks": False, "reason": "none", "answer_protected": True}

        def visual_leaks(self, **kwargs):
            self.visual_calls += 1
            return self.visual_calls == 1  # First visual leaks, second passes

        def check_math(self, **kwargs):
            return True

    model = VisualFixModel()
    judge = VisualLeakOnceJudge()
    trace = Recorder()
    with use_definitions(compact_catalog), trace.capture():
        res = run_tutor_turn(
            model,
            envelope={},
            instruction="画图帮我理解",
            window=[],
            images=[],
            tools=_tools(db),
            permit=TutorPermit(answer_protected=True, attempt_summary=AttemptSummary()),
            leak_judge=judge,
            task_title=None,
            problem_summary="小明有3份，小红有5份",
        )
    assert model.calls == 2
    # Text vetting was reused on visual-only redraw -> text judge called ONLY ONCE!
    assert judge.text_calls == 1
    assert judge.visual_calls == 2
    assert res.vetting is not None and res.vetting.failure is None
    assert res.vetting.visual is not None
    assert res.vetting.candidate.content == approved_content
    actions = [e["node_id"].split(".")[-1] for e in trace.events if e["kind"] == "action" and e["node_id"].split(".")[-1] in {"primary", "repair", "finish"}]
    assert actions == ["primary", "repair", "finish"]
