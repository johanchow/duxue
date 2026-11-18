import pytest

from app.application.commands.problem_solving import (
    ConfirmStemCommand,
    ExecuteDossierSolveCommand,
    RequestSolveCommand,
    VerifiedSolution,
    solve_and_verify_problem,
)
from app.application.queries.problem_dossier import GetProblemDossierQuery
from app.contexts.problem_solving.domain.dossier import StructuredStem
from app.infrastructure.math_engine.adapter import SubprocessMathEngineAdapter
from app.infrastructure.persistence.models import (
    Guardian,
    GuardianWard,
    User,
    Ward,
)


def _seed_wards(db) -> tuple[Ward, Ward]:
    u_g = User(type="guardian")
    u_w1 = User(type="ward")
    u_w2 = User(type="ward")
    db.add_all([u_g, u_w1, u_w2])
    db.flush()
    g = Guardian(id=u_g.id, email="ps_g@example.com", name="家长")
    w1 = Ward(id=u_w1.id, display_name="学生A", grade_stage="high_school")
    w2 = Ward(id=u_w2.id, display_name="学生B", grade_stage="high_school")
    db.add_all([g, w1, w2])
    db.flush()
    db.add_all([GuardianWard(guardian_id=g.id, ward_id=w1.id), GuardianWard(guardian_id=g.id, ward_id=w2.id)])
    db.flush()
    return w1, w2


class FakeSolverPort:
    """Controllable solver & stem-reader double for T1/T2 pipeline verification."""

    def __init__(self, *, t1_payload: dict | None, t2_routes: list[dict] | None = None, reread_stem: dict | None = None):
        self.t1_payload = t1_payload
        self.t2_routes = list(t2_routes or [])
        self.reread_stem = reread_stem
        self.solve_calls: list[str] = []
        self.reread_calls = 0

    def extract_stem(self, *, text: str, images: list[str], independent_reread: bool = False) -> dict | None:
        if independent_reread:
            self.reread_calls += 1
            return self.reread_stem
        return {"subject": "math", "raw_text": text, "subproblems": ["(1)"]}

    def solve_route(self, *, stem: StructuredStem, images: list[str], route_hint: str) -> dict | None:
        self.solve_calls.append(route_hint)
        if route_hint == "T1":
            return self.t1_payload
        idx = len([c for c in self.solve_calls if c.startswith("T2")]) - 1
        return self.t2_routes[idx] if 0 <= idx < len(self.t2_routes) else None


def test_t1_failed_anchor_escalates_to_t2_method_diverse_consensus_and_achieves_high_confidence(db):
    w1, w2 = _seed_wards(db)
    enqueued: list[str] = []

    # RequestSolve always locks student uploads to scope="ward" and is idempotent per fingerprint+ward
    req_cmd = RequestSolveCommand(db, enqueue_fn=lambda did: enqueued.append(did))
    r1 = req_cmd.execute(ward_id=w1.id, text="已知 f(x) = x**3 - 3*x，求导数与极值点", images=[])
    r2 = req_cmd.execute(ward_id=w1.id, text="已知  f(x)=x**3-3*x, 求导数与极值点。", images=[])
    assert r1.dossier_id == r2.dossier_id
    assert len(enqueued) == 1  # Deduped while pending lease is active!

    # Ward B asking the exact same text gets a strictly isolated ward-scoped dossier (no cross-student pollution)
    r_other = req_cmd.execute(ward_id=w2.id, text="已知 f(x) = x**3 - 3*x，求导数与极值点", images=[])
    assert r_other.dossier_id != r1.dossier_id

    # Unauthorized cross-ward read is strictly denied
    query = GetProblemDossierQuery(db)
    with pytest.raises(PermissionError):
        query.get_for_ward(ward_id=w2.id, dossier_id=r1.dossier_id)

    # T1 gives an unverified/wrong anchor -> automatically escalates to T2 with 2 method-diverse routes that agree!
    good_route = {
        "subject": "math",
        "final_answers": {"(1)": "{-1, 1}"},
        "scoring_points": [{"id": "SP1", "step": "求导 f'(x)=3x^2-3", "points": 3}],
        "implicit_constraints": [],
        "approaches": [
            {
                "id": "A1",
                "name": "求导因式分解法",
                "milestones": [
                    {
                        "id": "M1",
                        "goal": "求导",
                        "check_kind": "symbolic_equivalence",
                        "canonical_target": "3*x**2 - 3",
                        "verify_request": {
                            "op": "differentiate",
                            "args": {"expression": "x**3 - 3*x", "variable": "x", "order": 1},
                            "symbols": [{"name": "x", "domain": "real"}],
                            "assumptions": [],
                        },
                    }
                ],
            }
        ],
    }
    bad_t1 = {
        **good_route,
        "approaches": [
            {
                "id": "A1",
                "name": "错误初算",
                "milestones": [
                    {
                        "id": "M1",
                        "goal": "求导",
                        "check_kind": "symbolic_equivalence",
                        "canonical_target": "999*x",  # Wrong! Engine returns 3*x**2 - 3 != 999*x
                        "verify_request": {
                            "op": "differentiate",
                            "args": {"expression": "x**3 - 3*x", "variable": "x", "order": 1},
                            "symbols": [{"name": "x", "domain": "real"}],
                            "assumptions": [],
                        },
                    }
                ],
            }
        ],
    }
    solver = FakeSolverPort(t1_payload=bad_t1, t2_routes=[good_route, good_route])
    exec_cmd = ExecuteDossierSolveCommand(db, solver=solver, math_engine=SubprocessMathEngineAdapter())
    settled = exec_cmd.execute(dossier_id=r1.dossier_id, images=[])

    assert solver.solve_calls == ["T1", "T2_algebraic", "T2_alternative"]
    assert settled.tier == "T2"
    assert settled.status == "ready"
    assert settled.confidence == "high"


def test_t2_disagreement_or_image_reread_mismatch_falls_back_to_low_confidence_until_stem_confirmed(db):
    w1, _ = _seed_wards(db)
    req_cmd = RequestSolveCommand(db, enqueue_fn=lambda _did: None)
    r = req_cmd.execute(ward_id=w1.id, text="模糊图片题 f(x)=ax^2", images=["data:image/png;base64,iVBORw0KGgo="])

    route_a = {
        "subject": "math",
        "uncertain": True,
        "final_answers": {"(1)": "a=1"},
        "approaches": [{"id": "A1", "name": "路线1", "milestones": [{"id": "M1", "goal": "步1", "check_kind": "conceptual_rubric"}]}],
    }
    route_b = {
        "subject": "math",
        "final_answers": {"(1)": "a=2"},  # Disagrees with route_a!
        "approaches": [{"id": "A1", "name": "路线2", "milestones": [{"id": "M1", "goal": "步1", "check_kind": "conceptual_rubric"}]}],
    }
    # Independent image reread also spots a number discrepancy ("ax^3" vs "ax^2")
    solver = FakeSolverPort(
        t1_payload=route_a,
        t2_routes=[route_a, route_b],
        reread_stem={"subject": "math", "raw_text": "模糊图片题 f(x)=ax^3", "subproblems": ["(1)"]},
    )
    exec_cmd = ExecuteDossierSolveCommand(db, solver=solver, math_engine=SubprocessMathEngineAdapter())
    settled = exec_cmd.execute(dossier_id=r.dossier_id, images=["data:image/png;base64,iVBORw0KGgo="])

    assert solver.reread_calls == 1
    assert settled.status == "low_confidence"
    assert settled.confidence == "low"
    assert settled.stem.needs_student_confirmation is True

    # ConfirmStem increments stem_version, resets to pending, and triggers re-solve
    reenqueued: list[str] = []
    confirm_cmd = ConfirmStemCommand(db, enqueue_fn=lambda did: reenqueued.append(did))
    updated = confirm_cmd.execute(
        ward_id=w1.id,
        dossier_id=r.dossier_id,
        confirmed_text="确认题面为 f(x) = 2*x**2",
    )
    assert updated.stem.stem_version == 2
    assert updated.status == "pending"
    assert reenqueued == [r.dossier_id]


def test_stateless_solve_and_verify_problem_and_bank_only_query_never_leak_ward_dossiers(db):
    from app.application.ports.problem_solving import SqlProblemDossierRepository
    from app.contexts.problem_solving.domain.dossier import (
        ProblemDossier,
        compute_stem_fingerprint,
    )
    from app.infrastructure.persistence.models import now, uid

    w1, _ = _seed_wards(db)
    stem = StructuredStem(subject="math", raw_text="求函数 f(x) = x**2 - 4*x 的对称轴")
    fp = compute_stem_fingerprint(stem)

    # 1. Stateless solve_and_verify_problem works with zero DB dependency
    verified_t1 = {
        "subject": "math",
        "final_answers": {"main": "2"},
        "scoring_points": [{"id": "SP1", "step": "配方得 (x-2)^2 - 4", "points": 2}],
        "implicit_constraints": [],
        "approaches": [
            {
                "id": "A1",
                "name": "配方法",
                "milestones": [
                    {
                        "id": "M1",
                        "goal": "求导找驻点",
                        "check_kind": "symbolic_equivalence",
                        "canonical_target": "2*x - 4",
                        "verify_request": {
                            "op": "differentiate",
                            "args": {"expression": "x**2 - 4*x", "variable": "x", "order": 1},
                            "symbols": [{"name": "x", "domain": "real"}],
                            "assumptions": [],
                        },
                    }
                ],
            }
        ],
    }
    solver = FakeSolverPort(t1_payload=verified_t1)
    solution = solve_and_verify_problem(
        stem=stem,
        images=[],
        solver=solver,
        math_engine=SubprocessMathEngineAdapter(),
        initial_tier="T1",
    )
    assert isinstance(solution, VerifiedSolution)
    assert solution.status == "ready"
    assert solution.confidence == "medium"
    assert solution.final_answers == {"main": "2"}
    assert solver.solve_calls == ["T1"]

    # 2. Bank-only query ignores ward-scoped dossiers and returns only scope="bank" ready dossiers
    repo = SqlProblemDossierRepository(db)
    ward_dossier = ProblemDossier.create_pending(
        dossier_id=uid(), scope="ward", owner_ward_id=w1.id, stem=stem, tier="T1", solver_version="dossier.v1", now_at=now()
    ).complete_solve(
        approaches=solution.approaches,
        invariants=solution.invariants,
        scoring_points=solution.scoring_points,
        final_answers={"main": "ward-secret"},
        confidence="high",
        tier="T2",
        evidence={"route_count": 2},
    )
    repo.save(ward_dossier)
    query = GetProblemDossierQuery(db)
    assert query.find_bank_ready(fingerprint=fp) is None

    bank_dossier = ProblemDossier.create_pending(
        dossier_id=uid(), scope="bank", owner_ward_id=None, stem=stem, tier="T2", solver_version="dossier.v1", now_at=now()
    ).complete_solve(
        approaches=solution.approaches,
        invariants=solution.invariants,
        scoring_points=solution.scoring_points,
        final_answers={"main": "2"},
        confidence="high",
        tier="T2",
        evidence={"bank_matched": True},
    )
    repo.save(bank_dossier)
    found = query.find_bank_ready(fingerprint=fp)
    assert found is not None
    assert found.scope == "bank"
    assert found.owner_ward_id is None
    assert found.final_answers == {"main": "2"}
