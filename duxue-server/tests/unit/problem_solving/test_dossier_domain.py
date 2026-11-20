from datetime import datetime, timedelta, timezone

from app.application.workflows.blueprint_planner import verify_milestone_anchor
from app.contexts.problem_solving.domain.dossier import (
    DossierConfidencePolicy,
    ProblemDossier,
    ScoringPoint,
    StructuredStem,
    compute_stem_fingerprint,
)
from app.contexts.tutoring.domain.blueprint import Approach, Milestone
from app.infrastructure.math_engine.adapter import SubprocessMathEngineAdapter


def test_anchor_verification_rejects_mismatched_non_equivalence_canonical_target():
    engine = SubprocessMathEngineAdapter()
    # Non-equivalence op (`differentiate`) returns "2*x", NOT "3*x"!
    # Must return deterministic `contradicted` (four-state verification).
    bad_ms = {
        "id": "M1",
        "goal": "求导",
        "check_kind": "symbolic_equivalence",
        "canonical_target": "3*x",
        "verify_request": {
            "op": "differentiate",
            "args": {"expression": "x**2", "variable": "x", "order": 1},
            "symbols": [{"name": "x", "domain": "real"}],
            "assumptions": [],
        },
    }
    assert verify_milestone_anchor(engine, bad_ms) == "contradicted"

    good_ms = {
        **bad_ms,
        "canonical_target": "2*x",
    }
    assert verify_milestone_anchor(engine, good_ms) == "verified"

    # Missing engine or verify_request -> `unknown` (never falsely `contradicted`)
    assert verify_milestone_anchor(None, good_ms) == "unknown"
    assert verify_milestone_anchor(engine, {"id": "M0", "goal": "概念", "check_kind": "conceptual_rubric"}) == "not_applicable"

    # Solution set equality check: solve x**2 - 1 == 0 -> {-1, 1}
    good_solve = {
        "id": "M2",
        "goal": "求根",
        "check_kind": "solution_set_or_counterexample",
        "canonical_target": "{-1, 1}",
        "verify_request": {
            "op": "solve",
            "args": {"equations": ["x**2 - 1"], "variables": ["x"]},
            "symbols": [{"name": "x", "domain": "real"}],
            "assumptions": [],
        },
    }
    assert verify_milestone_anchor(engine, good_solve) == "verified"

    wrong_solve = {**good_solve, "canonical_target": "{1, 2}"}
    assert verify_milestone_anchor(engine, wrong_solve) == "contradicted"


def test_stem_fingerprint_normalizes_punctuation_whitespace_and_tex_fractions():
    s1 = StructuredStem(
        subject="math",
        raw_text="已知函数 f(x) = \\frac{1}{2}x^2 - \\ln x ，求单调区间。",
        subproblems=("(1) 求导；", "(2) 求极值。"),
    )
    s2 = StructuredStem(
        subject="math",
        raw_text="已知函数  f(x)=(1)/(2)x^2-ln x, 求单调区间!",
        subproblems=("(1) 求导;", "(2) 求极值"),
    )
    assert compute_stem_fingerprint(s1) == compute_stem_fingerprint(s2)

    # Changing a number MUST change the fingerprint
    s3 = StructuredStem(
        subject="math",
        raw_text="已知函数 f(x) = \\frac{1}{3}x^2 - \\ln x ，求单调区间。",
        subproblems=("(1) 求导；", "(2) 求极值。"),
    )
    assert compute_stem_fingerprint(s1) != compute_stem_fingerprint(s3)


def test_confidence_policy_escalation_and_dossier_lease_recovery():
    m_verified = Milestone(
        id="M1",
        goal="求导",
        check_kind="symbolic_equivalence",
        canonical_target="2*x",
        verification_status="verified",
    )
    m_unverified = Milestone(
        id="M2",
        goal="求根",
        check_kind="symbolic_equivalence",
        canonical_target="x=1",
        verification_status="unverified",
    )
    m_conceptual = Milestone(
        id="M3",
        goal="说明物理守恒条件",
        check_kind="conceptual_rubric",
        canonical_target="系统合外力为零",
        verification_status="not_applicable",
    )

    # Single-route output without bank hit is NEVER high; if computable anchor failed -> escalate T1 -> T2
    assert DossierConfidencePolicy.should_escalate_t1_to_t2(
        (Approach(id="A1", name="常规法", milestones=(m_verified, m_unverified)),),
        model_uncertain=False,
    ) is True
    assert DossierConfidencePolicy.should_escalate_t1_to_t2(
        (Approach(id="A1", name="常规法", milestones=(m_verified,)),),
        model_uncertain=False,
    ) is False

    # Two independent routes agree + all computable anchors verified -> high!
    conf_high = DossierConfidencePolicy.evaluate_confidence(
        bank_matched=False,
        route_count=2,
        routes_consistent=True,
        approaches=(Approach(id="A1", name="代数法", milestones=(m_verified,)),),
    )
    assert conf_high == "high"

    # Two independent routes agree, computable anchors verified, but has conceptual_rubric -> medium
    conf_med = DossierConfidencePolicy.evaluate_confidence(
        bank_matched=False,
        route_count=2,
        routes_consistent=True,
        approaches=(Approach(id="A1", name="动量法", milestones=(m_verified, m_conceptual)),),
    )
    assert conf_med == "medium"

    # Disagreement or single unverified route -> low
    assert (
        DossierConfidencePolicy.evaluate_confidence(
            bank_matched=False,
            route_count=2,
            routes_consistent=False,
            approaches=(Approach(id="A1", name="代数法", milestones=(m_verified,)),),
        )
        == "low"
    )

    # Lease expiration allows worker recovery from crashed pending job
    t0 = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
    stem = StructuredStem(subject="math", raw_text="求 f(x)=x^2 导数")
    dossier = ProblemDossier.create_pending(
        dossier_id="dos_1",
        scope="ward",
        owner_ward_id="ward_1",
        stem=stem,
        tier="T1",
        solver_version="v1",
        now_at=t0,
        lease_seconds=60,
    )
    assert dossier.can_acquire_solve_lease(t0 + timedelta(seconds=30)) is False
    assert dossier.can_acquire_solve_lease(t0 + timedelta(seconds=61)) is True

    settled = dossier.complete_solve(
        approaches=(Approach(id="A1", name="求导", milestones=(m_verified,)),),
        invariants=(),
        scoring_points=(ScoringPoint(id="S1", step="求导正确", points=4),),
        final_answers={"(1)": "2*x"},
        confidence="high",
        tier="T2",
        evidence={"route_count": 2, "routes_consistent": True},
    )
    assert settled.status == "ready"
    assert settled.confidence == "high"


def test_math_punctuation_and_case_are_part_of_problem_identity():
    for a, b in [("1.2 + 3", "12 + 3"), ("(1,23)", "(12,3)"), ("A+a", "a+a"), ("3!", "3")]:
        assert compute_stem_fingerprint(StructuredStem("math", a)) != compute_stem_fingerprint(StructuredStem("math", b))


def test_critical_condition_comparison_ignores_freeform_diagram_prose_and_checks_subproblem_completeness():
    from app.contexts.problem_solving.domain.dossier import compare_critical_conditions

    s1 = StructuredStem(
        subject="physics",
        raw_text="质量 m=2kg 的物块以 v=4m/s 滑行，求加速度 a",
        subproblems=("(1) 求加速度", "(2) 求位移"),
        diagram_summary="水平面上一个木块向右滑动",
    )
    s2 = StructuredStem(
        subject="physics",
        raw_text="质量 m=2kg 的物块以 v=4m/s 滑行，求加速度 a",
        subproblems=("(1) 求加速度", "(2) 求位移"),
        diagram_summary="粗糙水平轨道上的小滑块沿正方向运动",
    )
    agreed, reasons = compare_critical_conditions(s1, s2)
    assert agreed is True and reasons == ()

    s3 = StructuredStem(
        subject="physics",
        raw_text="质量 m=3kg 的物块以 v=4m/s 滑行，求加速度 a",
        subproblems=("(1) 求加速度", "(2) 求位移"),
    )
    agreed_diff, reasons_diff = compare_critical_conditions(s1, s3)
    assert agreed_diff is False and reasons_diff

    # Missing subproblem final answer blocks high/medium confidence
    comp = DossierConfidencePolicy.evaluate_subproblem_completeness(s1, {"(1)": "2 m/s^2"})
    assert comp["complete"] is False
    assert comp["missing_subproblems"] == ["(2) 求位移"]

    # Necessary-only check (e.g. physics dimension check) caps confidence at medium even on dual consistent routes
    m_dim = Milestone(
        id="M1",
        goal="检查量纲",
        check_kind="physics_dimension_and_eq",
        canonical_target="m/s^2",
        verification_status="verified",
    )
    assert (
        DossierConfidencePolicy.evaluate_confidence(
            bank_matched=False,
            route_count=2,
            comparison="consistent",
            approaches=(Approach(id="A1", name="牛顿第二定律", milestones=(m_dim,)),),
            subproblems_complete=True,
        )
        == "medium"
    )
    assert (
        DossierConfidencePolicy.evaluate_confidence(
            bank_matched=False,
            route_count=2,
            comparison="consistent",
            approaches=(Approach(id="A1", name="牛顿第二定律", milestones=(m_dim,)),),
            subproblems_complete=False,
        )
        == "low"
    )


def test_image_request_binding_survives_extraction_and_long_text():
    from unittest.mock import Mock

    from app.application.commands.problem_solving import RequestSolveCommand
    from app.application.ports.problem_solving import SqlProblemDossierRepository

    command = RequestSolveCommand(None, enqueue_fn=Mock())
    command.repo = Mock(spec=SqlProblemDossierRepository)
    command.repo.find_image_request.return_value = None
    command.repo.save.side_effect = lambda dossier: dossier
    question = "问" * 4000
    first = command.execute(ward_id="ward-a", text=question, images=["data:image/png;base64,YQ=="])
    other = command.execute(ward_id="ward-a", text=question, images=["data:image/png;base64,Yg=="])
    assert first.fingerprint != other.fingerprint
    assert first.stem.raw_text == other.stem.raw_text == question

    solved = first.complete_solve(
        approaches=(), invariants=(), scoring_points=(), final_answers={},
        confidence="medium", tier="T0", evidence={}, stem=StructuredStem("physics", "图中概念"),
    )
    assert (solved.status, solved.subject, solved.tier) == ("ready", "physics", "T0")
    assert solved.fingerprint == first.fingerprint
    assert solved.evidence["request_image_refs"] == first.evidence["request_image_refs"]
    command.repo.find_image_request.return_value = solved
    repeat = command.execute(ward_id="ward-a", text=question, images=["data:image/png;base64,YQ=="])
    command.repo.find_image_request.assert_called_with(ward_id="ward-a", fingerprint=solved.fingerprint)
    assert repeat.dossier_id == first.dossier_id
    assert command.enqueue_fn.call_count == 2
