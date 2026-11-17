import json

from app.application.commands.problem_solving import (
    ExecuteDossierSolveCommand,
)
from app.application.ports.companion import RunInvocation
from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.infrastructure.math_engine.adapter import SubprocessMathEngineAdapter
from app.infrastructure.persistence.models import (
    Guardian,
    GuardianWard,
    ProblemDossierRecord,
    TutoringProblem,
    User,
    Ward,
)


def _seed_ward(db) -> Ward:
    ug = User(type="guardian")
    uw = User(type="ward")
    db.add_all([ug, uw])
    db.flush()
    g = Guardian(id=ug.id, email="dt_g@example.com", name="家长")
    w = Ward(id=uw.id, display_name="高三小林", grade_stage="high_school")
    db.add_all([g, w])
    db.flush()
    db.add(GuardianWard(guardian_id=g.id, ward_id=w.id))
    db.flush()
    return w


class AllowAllSafety:
    def blocks_input(self, *, text: str) -> bool:
        return False

    def blocks_output(self, *, text: str | None) -> bool:
        return False


class HighConfidenceSolverDouble:
    def extract_stem(self, *, text: str, images: list[str], independent_reread: bool = False) -> dict | None:
        return {"subject": "math", "raw_text": text, "subproblems": ["(1)"]}

    def solve_route(self, *, stem, images: list[str], route_hint: str) -> dict | None:
        return {
            "subject": "math",
            "final_answers": {"(1)": "x = 2"},
            "scoring_points": [{"id": "SP1", "step": "移项得 2x=4", "points": 2}],
            "implicit_constraints": [{"id": "I1", "expression": "x > 0", "description": "正数条件"}],
            "approaches": [
                {
                    "id": "A1",
                    "name": "代数移项法",
                    "milestones": [
                        {
                            "id": "M1",
                            "goal": "移项合并同类项得 2x - 4 = 0",
                            "check_kind": "symbolic_equivalence",
                            "canonical_target": "{2}",
                            "verify_request": {
                                "op": "solve",
                                "args": {"equations": ["2*x - 4"], "variables": ["x"]},
                                "symbols": [{"name": "x", "domain": "real"}],
                                "assumptions": [],
                            },
                        }
                    ],
                }
            ],
        }


class RecordingTutorModel:
    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.envelopes: list[dict] = []

    def complete(self, *, envelope: dict, instruction: str, recent_utterances=None, current_images=None, repair_error=None, observations=None) -> dict:
        self.envelopes.append(envelope)
        return self.replies.pop(0)


class InspectingJudge:
    def __init__(self, *, affirms_student_answer: bool = False):
        self.affirms = affirms_student_answer
        self.summaries: list[str] = []

    def leaks(self, *, text: str, task_title: str | None, problem_summary: str | None, images=None):
        self.summaries.append(problem_summary or "")
        return {
            "leaks": False,
            "reason": "none",
            "answer_protected": True,
            "affirms_student_answer": self.affirms,
        }

    def check_math(self, *, text: str, context: dict, images: list[str]) -> bool | None:
        return True


def test_first_turn_nonblocking_when_dossier_pending_then_second_turn_adopts_ready_dossier(db):
    ward = _seed_ward(db)
    enqueued_ids: list[str] = []

    tutor_model = RecordingTutorModel(
        [
            # Turn 1: dossier is still pending (worker hasn't finished within 0s budget) -> safe Socratic icebreaker
            {
                "act": "guide",
                "content": "我们先一起读题确认条件：已知正数 $x$ 满足 $2x - 4 = 0$，你准备先怎么移项？",
                "turn": {
                    "type": "work",
                    "relation": "new",
                    "depth": "reasoning",
                    "student_move": "request_hint",
                    "next_subgoal": "移项整理方程",
                },
            },
            # Turn 2: background worker finished -> tutor receives ready dossier in envelope & advances student progress!
            {
                "act": "guide",
                "content": "移项得到 $2x = 4$ 非常准确！最后一步除以系数就能算出 $x$ 了。",
                "turn": {
                    "type": "work",
                    "relation": "same",
                    "depth": "reasoning",
                    "student_move": "attempt",
                    "progress": "some",
                    "evidence": "2x = 4",
                    "completed_milestone_id": "M1",
                    "next_subgoal": "求出 x",
                },
            },
        ]
    )
    judge = InspectingJudge(affirms_student_answer=False)
    wf = TutoringWorkflow(
        db,
        turn_model=tutor_model,
        leak_judge=judge,
        safety_screening=AllowAllSafety(),
        math_engine=SubprocessMathEngineAdapter(),
        dossier_enqueue_fn=lambda did, *_a: enqueued_ids.append(did),
        first_turn_solve_budget_seconds=0.0,
    )

    # Turn 1: non-blocking while dossier is pending
    out1 = wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-d1",
            run_id="r-1",
            turn_id="t-1",
            turn={"content": "已知正数 x 满足 2x - 4 = 0，求 x"},
        )
    )
    assert out1.next_interaction["act"] == "guide"
    assert len(enqueued_ids) == 1
    prob = db.query(TutoringProblem).one()
    assert prob.dossier_id == enqueued_ids[0]
    dossier_row = db.get(ProblemDossierRecord, prob.dossier_id)
    assert dossier_row is not None and dossier_row.status == "pending"

    # Simulate background `solving` Celery worker completing T2 high-confidence solve
    dossier_row.tier = "T2"
    db.flush()
    ExecuteDossierSolveCommand(
        db,
        solver=HighConfidenceSolverDouble(),
        math_engine=SubprocessMathEngineAdapter(),
    ).execute(dossier_id=prob.dossier_id, images=[])

    # Turn 2: automatically reads ready high-confidence dossier & records student milestone progress
    out2 = wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-d1",
            run_id="r-2",
            turn_id="t-2",
            context_refs=out1.context_refs,
            turn={"content": "我先移项得到 2x = 4"},
        )
    )
    assert out2.next_interaction["act"] == "guide"
    assert "problem_dossier" in tutor_model.envelopes[1]
    assert tutor_model.envelopes[1]["problem_dossier"]["confidence"] == "high"

    # Anti-false-positive guardrail: intermediate milestone canonical_target `{2}` or goal NEVER sent to leak-judge,
    # ONLY `verified_final_answers` when confidence == "high"!
    judge_payload = json.loads(judge.summaries[-1])
    inner_problem = json.loads(judge_payload["problem"]) if isinstance(judge_payload.get("problem"), str) else judge_payload
    assert inner_problem.get("verified_final_answers") == {"(1)": "x = 2"}
    assert "移项合并同类项" not in judge.summaries[-1]

    # Student's personal progress stored on TutoringProblem, NOT mutating ProblemDossierRecord
    db.refresh(prob)
    assert prob.milestone_progress == {"M1": "completed"}


def test_confidence_code_gate_blocks_unverified_verdict_assertion_when_dossier_low_or_pending(db):
    ward = _seed_ward(db)
    # Create a pending/low-confidence dossier (no background worker run yet, and tutor did NOT call math tool)
    tutor_model = RecordingTutorModel(
        [
            # Primary attempt: recklessly affirms student's unverified answer while dossier is still pending!
            {
                "act": "guide",
                "content": "你算得完全正确，答案就是 7！",
                "turn": {
                    "type": "work",
                    "relation": "new",
                    "depth": "reasoning",
                    "student_move": "attempt",
                    "progress": "submitted",
                    "evidence": "我猜答案是 7",
                },
            },
            # Repair attempt after code confidence gate denies unverified affirmation -> switches to Socratic check!
            {
                "act": "guide",
                "content": "我们可以把 $x=7$ 代回原方程左边算一算，看看两边是否相等？",
                "turn": {
                    "type": "work",
                    "relation": "new",
                    "depth": "reasoning",
                    "student_move": "attempt",
                    "progress": "some",
                    "evidence": "提出 x=7",
                    "next_subgoal": "代回原方程检验",
                },
            },
        ]
    )

    class TwoStepJudge:
        def __init__(self):
            self.calls = 0

        def leaks(self, *, text: str, task_title: str | None, problem_summary: str | None, images=None):
            self.calls += 1
            # First candidate affirms student answer; second candidate asks student to verify
            return {
                "leaks": False,
                "reason": "none",
                "answer_protected": True,
                "affirms_student_answer": self.calls == 1,
            }

        def check_math(self, *, text: str, context: dict, images: list[str]) -> bool | None:
            return True

    wf = TutoringWorkflow(
        db,
        turn_model=tutor_model,
        leak_judge=TwoStepJudge(),
        safety_screening=AllowAllSafety(),
        math_engine=SubprocessMathEngineAdapter(),
        dossier_enqueue_fn=lambda *_a: None,
        first_turn_solve_budget_seconds=0.0,
    )
    out = wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-gate",
            run_id="r-gate",
            turn_id="t-gate",
            turn={"content": "复杂的超越方程 ln x + x = 8，我算出来是 7 对不对？"},
        )
    )
    # First reply was blocked by the §4.4 code confidence gate and repaired into Socratic self-check!
    assert "代回原方程" in out.next_interaction["content"]
    assert "完全正确" not in out.next_interaction["content"]
