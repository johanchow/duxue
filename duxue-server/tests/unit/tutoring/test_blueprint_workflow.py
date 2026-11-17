from app.application.ports.companion import RunInvocation
from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.infrastructure.math_engine.adapter import SubprocessMathEngineAdapter
from app.infrastructure.persistence.models import (
    Guardian,
    GuardianWard,
    TutoringMessage,
    TutoringProblem,
    User,
    Ward,
)


class FakePlanner:
    def __init__(self):
        self.calls = 0

    def plan(self, *, content: str, images: list[str], prior_group: dict | None = None, grade_stage: str | None = None) -> dict | None:
        self.calls += 1
        return {
            "subject": "math",
            "shared_stem_ref": "stem_deriv_01",
            "shared_stem_summary": "已知函数 f(x) = ln(x) - a*x**2 + (2*a-1)*x",
            "subproblem_label": "(1)",
            "implicit_constraints": [
                {"id": "I1", "expression": "x > 0", "description": "对数定义域"}
            ],
            "approaches": [
                {
                    "id": "A1",
                    "name": "求导通分分类讨论",
                    "milestones": [
                        {
                            "id": "M1",
                            "goal": "求导并通分因式分解",
                            "check_kind": "symbolic_equivalence",
                            "canonical_target": "-(2*a*x + 1)*(x - 1)/x",
                            "verify_request": {
                                "op": "equivalent",
                                "args": {
                                    "left": "1/x - 2*a*x + (2*a - 1)",
                                    "right": "-(2*a*x + 1)*(x - 1)/x",
                                },
                                "symbols": [
                                    {"name": "x", "domain": "real"},
                                    {"name": "a", "domain": "real"},
                                ],
                                "assumptions": ["x:positive"],
                            },
                            "common_pitfalls": ["忘写 x>0"],
                        },
                        {
                            "id": "M2",
                            "goal": "按 a<=0, 0<a<1/2, a=1/2, a>1/2 讨论单调区间",
                            "check_kind": "solution_set_or_counterexample",
                            "canonical_target": "a=0, a=1/2 为临界点",
                            "verify_request": {
                                # Intentionally false claim to test pre-verification downgrade!
                                "op": "equivalent",
                                "args": {"left": "1 + 1", "right": "5"},
                                "symbols": [],
                                "assumptions": [],
                            },
                        },
                    ],
                }
            ],
        }


class CapturingTutorModel:
    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.envelopes: list[dict] = []
        self.instructions: list[str] = []

    def complete(self, *, envelope: dict, instruction: str, recent_utterances=None, current_images=None, repair_error=None, observations=None) -> dict:
        self.envelopes.append(envelope)
        self.instructions.append(instruction)
        return self.replies.pop(0)


class StrictJudge:
    def __init__(self, *, deny_substring: str | None = None):
        self.deny_substring = deny_substring
        self.seen_summaries: list[str] = []

    def leaks(self, *, text: str, task_title: str | None, problem_summary: str | None, images=None):
        self.seen_summaries.append(problem_summary or "")
        if self.deny_substring and self.deny_substring in text:
            return {"leaks": True, "reason": "complete_solution", "answer_protected": True}
        return {"leaks": False, "reason": "none", "answer_protected": True}

    def check_math(self, *, text: str, context: dict, images: list[str]) -> bool | None:
        return True


class AllowAllSafety:
    def blocks_input(self, *, text: str) -> bool:
        return False

    def blocks_output(self, *, text: str | None) -> bool:
        return False


def _seed_high_school_ward(db) -> Ward:
    g_user = User(type="guardian")
    w_user = User(type="ward")
    db.add_all([g_user, w_user])
    db.flush()
    guardian = Guardian(id=g_user.id, email="g_bp@example.com", name="家长")
    ward = Ward(id=w_user.id, display_name="高二小陈", grade_stage="high_school")
    db.add_all([guardian, ward])
    db.flush()
    db.add(GuardianWard(guardian_id=guardian.id, ward_id=ward.id))
    db.flush()
    return ward


def test_blueprint_preverified_persisted_privately_and_advanced_across_turns_and_subproblems(db):
    db_session = db
    ward = _seed_high_school_ward(db_session)
    planner = FakePlanner()
    tutor_model = CapturingTutorModel(
        [
            # Turn 1: new reasoning problem
            {
                "act": "guide",
                "content": "我们先确定函数 $f(x)$ 的定义域，再求出导函数 $f'(x)$ 并通分，你先试试？",
                "turn": {
                    "type": "work",
                    "relation": "new",
                    "depth": "reasoning",
                    "student_move": "request_hint",
                    "next_subgoal": "写出定义域并求 f'(x) 通分式",
                },
            },
            # Turn 2: student completes M1
            {
                "act": "guide",
                "content": "导函数通分因式分解完全正确！接下来观察分子二次项系数，应该先对参数 $a$ 做哪两类划分？",
                "turn": {
                    "type": "work",
                    "relation": "same",
                    "depth": "reasoning",
                    "student_move": "attempt",
                    "progress": "some",
                    "evidence": "定义域 x>0, f'(x) = -(2ax-1)(x-1)/x",
                    "completed_milestone_id": "M1",
                    "next_subgoal": "讨论二次项系数 a=0 与 a!=0",
                },
            },
            # Turn 3: student moves to subproblem (2) of the same stem!
            {
                "act": "guide",
                "content": "进入第 (2) 问恒成立问题，我们可以结合第 (1) 问求出的单调区间来找最大值。",
                "turn": {
                    "type": "work",
                    "relation": "subproblem",
                    "subproblem_label": "(2)",
                    "verified_prior_conclusion": "当 a=1 时 f(x) 在 (0,1/2) 递减、(1/2,1) 递增、(1,+oo) 递减",
                    "depth": "reasoning",
                    "student_move": "request_hint",
                    "next_subgoal": "分析端点与极值点函数值符号",
                },
            },
        ]
    )
    judge = StrictJudge(deny_substring="直接给你全套答案")

    wf = TutoringWorkflow(
        db_session,
        turn_model=tutor_model,
        leak_judge=judge,
        safety_screening=AllowAllSafety(),
        math_engine=SubprocessMathEngineAdapter(),
        blueprint_planner=planner,
    )

    # --- Turn 1 ---
    out1 = wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-1",
            run_id="run-1",
            turn_id="turn-1",
            turn={"content": "已知 f(x)=ln x - a x^2 + (2a-1)x，(1) 讨论单调区间，没思路"},
        )
    )
    assert out1.next_interaction["act"] == "guide"
    # Client payload MUST NEVER expose internal_blueprint
    assert "internal_blueprint" not in out1.next_interaction
    assert "canonical_target" not in str(out1.next_interaction)
    # Leak judge summary MUST NEVER contain blueprint canonical targets
    assert "-(2*a*x + 1)*(x - 1)/x" not in judge.seen_summaries[-1]

    prob1 = db_session.query(TutoringProblem).one()
    assert prob1.internal_blueprint is not None
    ms_list = prob1.internal_blueprint["approaches"][0]["milestones"]
    # M1 verified by SubprocessMathEngineAdapter -> verified; M2 (1+1==5) -> downgraded to unverified!
    assert ms_list[0]["verification_status"] == "verified"
    assert ms_list[1]["verification_status"] == "unverified"
    assert planner.calls == 1

    # --- Turn 2: reuses persisted blueprint without calling planner again, advances M1 -> M2 ---
    out2 = wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-1",
            run_id="run-2",
            turn_id="turn-2",
            context_refs=out1.context_refs,
            turn={"content": "定义域 x>0，我通分算出 f'(x) = -(2ax-1)(x-1)/x"},
        )
    )
    assert out2.next_interaction["act"] == "guide"
    assert planner.calls == 1  # Not re-planned on same problem!
    # Turn 2 model received private blueprint in envelope
    assert tutor_model.envelopes[1].get("internal_blueprint") is not None
    db_session.refresh(prob1)
    assert prob1.internal_blueprint["active_milestone_id"] == "M2"
    assert prob1.internal_blueprint["approaches"][0]["milestones"][0]["student_status"] == "completed"

    # --- Turn 3: subproblem (2) archives prob1, keeps at most 1 open problem, inherits prior conclusion ---
    out3 = wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-1",
            run_id="run-3",
            turn_id="turn-3",
            context_refs=out2.context_refs,
            turn={"content": "第(1)问懂了，接着看第(2)问：若 f(x) <= 0 恒成立，求 a 的范围"},
        )
    )
    assert out3.next_interaction["act"] == "guide"
    all_probs = db_session.query(TutoringProblem).order_by(TutoringProblem.created_at.asc()).all()
    assert len(all_probs) == 2
    assert all_probs[0].status == "abandoned"
    assert all_probs[1].status == "open"
    assert all_probs[1].group_context["shared_stem_ref"] == "stem_deriv_01"
    assert all_probs[1].group_context["subproblem_label"] == "(2)"
    assert len(all_probs[1].group_context["prior_conclusions"]) == 1

    # Messages stored in DB never contain blueprint internals
    for msg in db_session.query(TutoringMessage).all():
        assert "canonical_target" not in msg.content


def test_leak_judge_still_blocks_tutor_reciting_blueprint_target_and_falls_back(db):
    ward = _seed_high_school_ward(db)
    planner = FakePlanner()
    tutor_model = CapturingTutorModel(
        [
            {
                "act": "guide",
                "content": "直接给你全套答案：导数是 -(2*a*x+1)*(x-1)/x，a<=0 时递增。",
                "turn": {"type": "work", "relation": "new", "depth": "reasoning", "student_move": "request_answer"},
            },
            {
                "act": "guide",
                "content": "直接给你全套答案：还是把完整分类全写给你。",
                "turn": {"type": "work", "relation": "new", "depth": "reasoning", "student_move": "request_answer"},
            },
        ]
    )
    judge = StrictJudge(deny_substring="直接给你全套答案")
    wf = TutoringWorkflow(
        db,
        turn_model=tutor_model,
        leak_judge=judge,
        safety_screening=AllowAllSafety(),
        math_engine=SubprocessMathEngineAdapter(),
        blueprint_planner=planner,
    )
    out = wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-leak",
            run_id="run-leak",
            turn_id="turn-leak",
            turn={"content": "直接把这道导数压轴题全过程写出来"},
        )
    )
    assert out.next_interaction["model_fallback"] is True
    assert "直接给你全套答案" not in out.next_interaction["content"]
    assert db.query(TutoringProblem).count() == 0
    assert planner.calls == 0
