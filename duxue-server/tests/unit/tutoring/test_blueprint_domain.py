from app.application.workflows.math_verification import MathVerification
from app.contexts.tutoring.domain.blueprint import (
    Approach,
    BlueprintProgressPolicy,
    Milestone,
    ProblemGroupContext,
    ProblemInvariant,
    SolutionBlueprint,
    VerifiedPriorConclusion,
)
from app.contexts.tutoring.domain.tutor_permit import ProblemState, TutorPermitPolicy
from app.infrastructure.math_engine.adapter import SubprocessMathEngineAdapter


def test_solution_blueprint_multi_approach_switch_and_never_unlocks_disclosure():
    bp = SolutionBlueprint(
        subject="math",
        problem_digest="digest_001",
        implicit_constraints=(
            ProblemInvariant(id="I1", expression="x > 0", description="对数真数大于0"),
        ),
        approaches=(
            Approach(
                id="A1",
                name="导数通分分类讨论",
                milestones=(
                    Milestone(
                        id="M1",
                        goal="求导并通分因式分解",
                        check_kind="symbolic_equivalence",
                        canonical_target="-(2*a*x - 1)*(x - 1)/x",
                        verification_status="verified",
                    ),
                    Milestone(
                        id="M2",
                        goal="分类讨论 a=0 与 a>0 两根大小",
                        check_kind="solution_set_or_counterexample",
                        canonical_target="a == 0 or a == 1/2",
                        verification_status="verified",
                    ),
                ),
            ),
            Approach(
                id="A2",
                name="参变分离法",
                milestones=(
                    Milestone(
                        id="B1",
                        goal="分离参数 a 与含 x 函数",
                        check_kind="symbolic_equivalence",
                        canonical_target="(x - ln(x))/(x**2 - 2*x)",
                        verification_status=" unverified".strip(),  # type: ignore[arg-type]
                    ),
                ),
            ),
        ),
        active_approach_id="A1",
        active_milestone_id="M1",
    )

    # Complete M1 -> automatically advances to M2 in A1
    bp_after_m1 = BlueprintProgressPolicy.advance(
        bp,
        completed_milestone_id="M1",
    )
    assert bp_after_m1.active_approach_id == "A1"
    assert bp_after_m1.active_milestone_id == "M2"
    m1_state = bp_after_m1.find_milestone("M1")
    assert m1_state is not None and m1_state.student_status == "completed"

    # Student switches to alternate valid approach A2 (milestone B1)
    bp_switched = BlueprintProgressPolicy.advance(
        bp,
        adopted_approach_id="A2",
    )
    assert bp_switched.active_approach_id == "A2"
    assert bp_switched.active_milestone_id == "B1"

    # Blueprint attachment NEVER unlocks TutorPermit.answer_protected
    p_state = ProblemState(status="open", active_subgoal="求导")
    permit = TutorPermitPolicy.permit(p_state)
    assert permit.answer_protected is True

    # JSON roundtrip preserves value-object equality
    restored = SolutionBlueprint.from_dict(bp_after_m1.to_dict())
    assert restored == bp_after_m1


def test_problem_group_context_inherits_verified_prior_conclusions():
    initial_group = ProblemGroupContext(
        shared_stem_ref="stem_ellipse_2026",
        shared_stem_summary="已知椭圆 C: x^2/a^2 + y^2/b^2 = 1 离心率 e=1/2，过点 (1, 3/2)",
        subproblem_label="(1)",
    )
    next_group = initial_group.advance_to_subproblem(
        next_label="(2)",
        verified_conclusion=VerifiedPriorConclusion(
            subproblem_label="(1)",
            conclusion="x**2/4 + y**2/3 = 1",
        ),
    )
    assert next_group.shared_stem_ref == "stem_ellipse_2026"
    assert next_group.subproblem_label == "(2)"
    assert len(next_group.prior_conclusions) == 1
    assert next_group.prior_conclusions[0].conclusion == "x**2/4 + y**2/3 = 1"
    assert ProblemGroupContext.from_dict(next_group.to_dict()) == next_group


def test_multiline_derivation_chain_locates_first_broken_step():
    engine = SubprocessMathEngineAdapter()
    ledger = MathVerification(
        engine,
        {"turn_id": "t1", "run_id": "r1", "problem_ref": "p1", "instruction_digest": "d1"},
        set(),
    )
    # Student solves (x - 2)**2 = 9:
    # Step 1: (x - 2)**2 - 9
    # Step 2: x**2 - 4*x + 4 - 9  (equal to Step 1)
    # Step 3: x**2 - 4*x + 5      (WRONG! 4 - 9 = -5, not +5)
    # Step 4: (x - 5)*(x + 1)
    chain_report = ledger.verify_derivation_chain(
        steps=[
            "(x - 2)**2 - 9",
            "x**2 - 4*x + 4 - 9",
            "x**2 - 4*x + 5",
            "(x - 5)*(x + 1)",
        ],
        symbols=[{"name": "x", "domain": "real"}],
    )
    assert chain_report["first_error_transition"] == {"from_step": 2, "to_step": 3}
    assert chain_report["transitions"][0]["verdict"] == "equal"
    assert chain_report["transitions"][1]["verdict"] == "not_equal"
