"""P0 boundaries: no unauthorized effects and no unverified delivery."""

import pytest

from app.application.agent.gates import GateRunner
from app.application.agent.orchestrator import EduAgentOrchestrator, OrchestratorStep
from app.application.agent.registry import ToolContext, ToolExecutor
from app.application.agent.role_policy import evaluate_role_policy
from app.application.commands.workspace_documents import honest
from app.application.tools.core_tools import build_default_registries
from app.application.workflows import education_workspace as workspace


@pytest.mark.parametrize(
    "role,tool,args,active,error",
    [
        (
            "ward",
            "problem_solving.solve_and_verify",
            {"prompt": "直接给答案"},
            {"problem_solving.solve_and_verify"},
            "tool_not_permitted",
        ),
        (
            "guardian",
            "artifact.create_or_revise",
            {"artifact_type": "lesson_pack"},
            {"math.compute"},
            "tool_not_permitted",
        ),
        ("guardian", "math.compute", {}, {"math.compute"}, "invalid_tool_input"),
    ],
)
def test_rejected_tool_request_never_invokes_handler(role, tool, args, active, error):
    tools, _ = build_default_registries()
    effects = []
    tools.register_handler(tool, lambda *_: effects.append("called") or {})
    result = ToolExecutor(tools).execute(
        tool_id=tool,
        args=args,
        ctx=ToolContext(actor_id="test", actor_role=role),
        policy=evaluate_role_policy(role=role),
        active_tools=frozenset(active),
    )
    assert result.error_code == error
    assert result.data == {}
    assert effects == []


@pytest.mark.parametrize("phase", ["write", "respond"])
@pytest.mark.parametrize("verdict", [False, 1, "error"])
def test_required_gate_failure_blocks_effect_or_candidate_delivery(phase, verdict):
    tools, skills = build_default_registries()
    effects = []
    tools.register_handler(
        "artifact.create_or_revise", lambda *_: effects.append("write") or {}
    )

    def gate(current_phase, candidate):
        if current_phase != phase:
            return True
        if verdict == "error":
            raise RuntimeError("gate unavailable")
        return verdict

    def planner(state):
        if not state["active_skill"]:
            return OrchestratorStep(action="load_skill", skill_id="edu.lesson_pack")
        if not effects:
            return OrchestratorStep(
                action="call_tool",
                tool_id="artifact.create_or_revise",
                tool_args={"artifact_type": "lesson_pack"},
            )
        return OrchestratorStep(action="respond", content="UNREVIEWED_CANDIDATE")

    result = EduAgentOrchestrator(
        tool_registry=tools,
        skill_registry=skills,
        gates=GateRunner({"artifact.verification_honesty": gate}),
    ).run(
        ctx=ToolContext(actor_id="test", actor_role="guardian"),
        message="生成材料",
        planner=planner,
    )
    assert result.status == "failed"
    assert result.artifact_id is None
    assert "UNREVIEWED_CANDIDATE" not in result.content
    assert effects == ([] if phase == "write" else ["write"])


def test_invalid_tool_output_cannot_be_used_for_delivery():
    tools, skills = build_default_registries()
    spec = tools.get_spec("math.compute").model_copy(
        update={
            "output_schema": {
                "type": "object",
                "required": ["answer"],
                "properties": {"answer": {"type": "number"}},
            },
        }
    )
    tools.register_spec(spec)
    tools.register_handler("math.compute", lambda *_: {"answer": "unverified"})
    steps = []

    def planner(state):
        steps.append(state["step_index"])
        return OrchestratorStep(
            action="call_tool", tool_id="math.compute", tool_args={"op": "test"}
        )

    result = EduAgentOrchestrator(tool_registry=tools, skill_registry=skills).run(
        ctx=ToolContext(actor_id="test", actor_role="guardian"),
        message="计算",
        planner=planner,
    )
    assert result.status == "failed"
    assert result.tool_results[-1].error_code == "invalid_tool_output"
    assert result.tool_results[-1].data == {}
    assert "unverified" not in result.content
    assert steps == [0]


@pytest.mark.parametrize("failure", ["no_evidence", "solver_error"])
def test_grading_without_reliable_solution_never_guesses_correctness(
    monkeypatch, failure
):
    comparisons = []

    def verify(stem):
        if failure == "solver_error":
            raise RuntimeError("solver unavailable")
        return {}

    monkeypatch.setattr(workspace, "verify", verify)
    monkeypatch.setattr(workspace, "proposal", lambda *_: comparisons.append(True))
    result = workspace.assess(
        {
            "kind": "grading_item",
            "label": "1",
            "legible": True,
            "stem": "3+4",
            "student_answer": "7",
        }
    )
    assert result["status"] == "needs_manual_review"
    assert result["needs_manual_review"] is True
    assert comparisons == []


def test_verified_question_edit_invalidates_previous_evidence():
    block = {
        "kind": "variant_question",
        "label": "1",
        "stem": "3+4",
        "status": "verified",
        "needs_manual_review": False,
        "reference_answers": {"main": "7"},
    }
    doc = workspace.Document(
        "lesson_pack",
        "加法",
        [block],
        verified_items=(workspace.evidence_digest(block),),
    )
    assert honest("respond", doc)
    block["stem"] = "3+5"
    assert not honest("write", doc)
    assert not honest("respond", doc)
