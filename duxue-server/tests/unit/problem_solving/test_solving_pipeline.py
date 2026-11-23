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
    """Controllable solver & stem-reader double for T1/backup/T2 pipeline verification."""

    def __init__(
        self,
        *,
        t1_payload: dict | None,
        backup_payload: dict | None = None,
        t2_routes: list[dict] | None = None,
        reread_stem: dict | None = None,
        timeout_once_hints: set[str] | None = None,
    ):
        self.t1_payload = t1_payload
        self.backup_payload = backup_payload
        self.t2_routes = list(t2_routes or [])
        self.reread_stem = reread_stem
        self.timeout_once_hints = set(timeout_once_hints or ())
        self.solve_calls: list[str] = []
        self.feedbacks: list[dict | None] = []
        self.reread_calls = 0

    def extract_stem(self, *, text: str, images: list[str], independent_reread: bool = False) -> dict | None:
        if independent_reread:
            self.reread_calls += 1
            return self.reread_stem
        return {"subject": "math", "raw_text": text, "subproblems": ["(1)"]}

    def solve_route(
        self,
        *,
        stem: StructuredStem,
        images: list[str],
        route_hint: str,
        feedback: dict | None = None,
    ) -> dict | None:
        self.solve_calls.append(route_hint)
        self.feedbacks.append(feedback)
        if route_hint in self.timeout_once_hints:
            self.timeout_once_hints.remove(route_hint)
            raise TimeoutError("simulated_timeout")
        if route_hint == "T1":
            return self.t1_payload
        if route_hint == "T1_backup":
            return self.backup_payload
        if route_hint == "T2_algebraic":
            return self.t2_routes[0] if len(self.t2_routes) > 0 else None
        if route_hint == "T2_alternative":
            return self.t2_routes[1] if len(self.t2_routes) > 1 else None
        return None


def test_t1_contradicted_anchor_uses_heterogeneous_backup_without_t2_escalation(db):
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

    # T1 gives a contradicted anchor -> does NOT escalate to T2; routes to heterogeneous `T1_backup` with feedback!
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
                        "canonical_target": "999*x",  # Contradicted! Engine returns 3*x**2 - 3 != 999*x
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
    solver = FakeSolverPort(t1_payload=bad_t1, backup_payload=good_route)
    exec_cmd = ExecuteDossierSolveCommand(db, solver=solver, math_engine=SubprocessMathEngineAdapter())
    settled = exec_cmd.execute(dossier_id=r1.dossier_id, images=[])

    assert solver.solve_calls == ["T1", "T1_backup"]
    assert solver.feedbacks[1] and solver.feedbacks[1]["contradictions"]
    assert settled.tier == "T1"
    assert settled.status == "ready"
    assert settled.confidence == "medium"
    assert settled.evidence["used_backup"] is True


def test_t2_disagreement_or_image_reread_mismatch_falls_back_to_low_confidence_until_stem_confirmed(db):
    w1, _ = _seed_wards(db)
    req_cmd = RequestSolveCommand(db, enqueue_fn=lambda _did: None)
    r = req_cmd.execute(
        ward_id=w1.id,
        text="模糊图片题 f(x)=ax^2",
        images=["data:image/png;base64,iVBORw0KGgo="],
        initial_tier="T1",
    )

    bad_t1 = {
        "subject": "math",
        "final_answers": {"(1)": "999"},
        "approaches": [
            {
                "id": "A1",
                "name": "路线1",
                "milestones": [
                    {
                        "id": "M1",
                        "goal": "求导",
                        "check_kind": "symbolic_equivalence",
                        "canonical_target": "999*x",
                        "verify_request": {
                            "op": "differentiate",
                            "args": {"expression": "x**2", "variable": "x", "order": 1},
                            "symbols": [{"name": "x", "domain": "real"}],
                            "assumptions": [],
                        },
                    }
                ],
            }
        ],
    }
    # Independent image reread spots a critical exponent discrepancy ("ax^3" vs "ax^2") -> short-circuits before backup!
    solver = FakeSolverPort(
        t1_payload=bad_t1,
        reread_stem={"subject": "math", "raw_text": "模糊图片题 f(x)=ax^3", "subproblems": ["(1)"]},
    )
    exec_cmd = ExecuteDossierSolveCommand(db, solver=solver, math_engine=SubprocessMathEngineAdapter())
    settled = exec_cmd.execute(dossier_id=r.dossier_id, images=["data:image/png;base64,iVBORw0KGgo="])

    assert solver.reread_calls == 1
    assert solver.solve_calls == ["T1"]  # Short-circuited on reread dispute!
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


def test_t1_timeout_retries_once_and_t2_eliminates_contradicted_route():
    good_route = {
        "subject": "math",
        "final_answers": {"(1)": "2*x"},
        "approaches": [
            {
                "id": "A1",
                "name": "求导法",
                "milestones": [
                    {
                        "id": "M1",
                        "goal": "求导",
                        "check_kind": "symbolic_equivalence",
                        "canonical_target": "2*x",
                        "verify_request": {
                            "op": "differentiate",
                            "args": {"expression": "x**2", "variable": "x", "order": 1},
                            "symbols": [{"name": "x", "domain": "real"}],
                            "assumptions": [],
                        },
                    }
                ],
            }
        ],
    }
    bad_route = {
        **good_route,
        "final_answers": {"(1)": "9*x"},
        "approaches": [
            {
                "id": "A2",
                "name": "错误路线",
                "milestones": [
                    {
                        "id": "M1",
                        "goal": "求导",
                        "check_kind": "symbolic_equivalence",
                        "canonical_target": "9*x",
                        "verify_request": {
                            "op": "differentiate",
                            "args": {"expression": "x**2", "variable": "x", "order": 1},
                            "symbols": [{"name": "x", "domain": "real"}],
                            "assumptions": [],
                        },
                    }
                ],
            }
        ],
    }
    stem = StructuredStem(subject="math", raw_text="求 f(x)=x^2 导数", subproblems=("(1)",))
    engine = SubprocessMathEngineAdapter()

    # 1. Timeout retries once in-place without escalating to T2
    solver_retry = FakeSolverPort(t1_payload=good_route, timeout_once_hints={"T1"})
    sol_t1 = solve_and_verify_problem(stem=stem, solver=solver_retry, math_engine=engine, initial_tier="T1")
    assert solver_retry.solve_calls == ["T1", "T1"]
    assert sol_t1.status == "ready"
    assert sol_t1.confidence == "medium"

    # 2. T2 parallel dual routes: one route contradicted -> eliminated, surviving verified route retained
    solver_t2 = FakeSolverPort(t1_payload=None, t2_routes=[bad_route, good_route])
    sol_t2 = solve_and_verify_problem(stem=stem, solver=solver_t2, math_engine=engine, initial_tier="T2")
    assert set(solver_t2.solve_calls) == {"T2_algebraic", "T2_alternative"}
    assert sol_t2.evidence["eliminated_route"] == "T2_algebraic"
    assert sol_t2.final_answers == {"(1)": "2*x"}
    assert sol_t2.status == "ready"
    assert sol_t2.confidence == "medium"


def test_stateless_solve_and_verify_problem_and_bank_only_query_never_leak_ward_dossiers(db):
    from app.application.ports.problem_solving import SqlProblemDossierRepository
    from app.contexts.problem_solving.domain.dossier import (
        ProblemDossier,
    )
    from app.infrastructure.persistence.models import now, uid

    w1, _ = _seed_wards(db)
    stem = StructuredStem(subject="math", raw_text="求函数 f(x) = x**2 - 4*x 的对称轴")

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
    assert query.find_bank_ready(stem=stem) is None

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
    found = query.find_bank_ready(stem=stem)
    assert found is not None
    assert found.scope == "bank"
    assert found.owner_ward_id is None
    assert found.final_answers == {"main": "2"}


def test_legacy_bank_collision_requires_matching_stored_stem(db):
    from dataclasses import replace

    from app.application.ports.problem_solving import SqlProblemDossierRepository
    from app.contexts.problem_solving.domain.dossier import (
        ProblemDossier,
        compute_stem_fingerprint,
    )
    from app.infrastructure.persistence.models import now, uid

    decimal = StructuredStem("math", "1.2+3")
    integer = StructuredStem("math", "12+3")
    old_fp = compute_stem_fingerprint(decimal, legacy=True)
    assert old_fp == compute_stem_fingerprint(integer, legacy=True)
    repo = SqlProblemDossierRepository(db)
    dossier = ProblemDossier.create_pending(
        dossier_id=uid(), scope="bank", owner_ward_id=None, stem=decimal,
        tier="T1", solver_version="v1", now_at=now(),
    )
    repo.save(replace(dossier, status="ready", fingerprint=old_fp))
    assert repo.find_bank_ready(stem=integer) is None
    assert repo.find_bank_ready(stem=decimal).dossier_id == dossier.dossier_id


def test_request_solve_defers_dispatch_until_commit_and_discards_on_rollback(db):
    w1, _ = _seed_wards(db)
    db.commit()
    enqueued: list[str] = []

    cmd = RequestSolveCommand(
        db,
        enqueue_fn=lambda did, _imgs=None: enqueued.append(did),
        defer_until_commit=True,
    )
    rolled_back = cmd.execute(ward_id=w1.id, text="求解 x + 1 = 2", images=[])
    assert enqueued == []  # Must NOT dispatch before commit!
    db.rollback()
    assert enqueued == []  # Rolled-back transaction must discard queued dispatch!

    committed = cmd.execute(ward_id=w1.id, text="求解 x + 2 = 5", images=[])
    assert committed.dossier_id != rolled_back.dossier_id
    assert enqueued == []
    db.commit()
    assert enqueued == [committed.dossier_id]


def test_execute_dossier_solve_rejects_stale_stem_version_overwrite(db):
    w1, _ = _seed_wards(db)
    req_cmd = RequestSolveCommand(db, enqueue_fn=lambda _did: None)
    dossier = req_cmd.execute(ward_id=w1.id, text="原题 2x = 6", images=[])
    db.commit()

    class StemBumpingSolver:
        def extract_stem(self, *, text: str, images: list[str], independent_reread: bool = False):
            return {"subject": "math", "raw_text": text, "subproblems": ["(1)"]}

        def solve_route(self, *, stem, images: list[str], route_hint: str, feedback=None):
            # Simulate student confirming a corrected stem (v1 -> v2) while v1 solve was in flight!
            ConfirmStemCommand(db, enqueue_fn=lambda _did: None).execute(
                ward_id=w1.id,
                dossier_id=dossier.dossier_id,
                confirmed_text="更正后 2x = 10",
                images=[],
            )
            db.commit()
            return {
                "subject": "math",
                "final_answers": {"(1)": "3"},
                "approaches": [
                    {
                        "id": "A1",
                        "name": "旧题面解",
                        "milestones": [{"id": "M1", "goal": "解 2x=6", "check_kind": "conceptual_rubric"}],
                    }
                ],
            }

    result = ExecuteDossierSolveCommand(
        db, solver=StemBumpingSolver(), math_engine=SubprocessMathEngineAdapter()
    ).execute(dossier_id=dossier.dossier_id, images=[])

    # Stale v1 solve must NOT overwrite v2 confirmed stem!
    assert result.stem.stem_version == 2
    assert result.stem.raw_text == "更正后 2x = 10"
    assert result.status == "pending"
    assert result.final_answers == {}
