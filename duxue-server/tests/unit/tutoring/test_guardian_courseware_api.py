"""API contract tests for /guardian/courseware/* endpoints."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import Principal, current_guardian
from app.api.v1 import guardian_courseware as gc_api
from app.application.commands.mentor_courseware import MentorCoursewareCommandService
from app.application.ports.mentor_courseware import (
    DirectorDraftResult,
    PedagogicalDirectorPort,
    PedagogicalJudgePort,
    PedagogicalJudgeResult,
    ProblemVerificationPort,
)
from app.application.process_managers.mentor_courseware_orchestrator import (
    MentorCoursewareOrchestrator,
)
from app.application.queries.mentor_courseware import MentorCoursewareQueryService
from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareStep,
    VerificationBaseline,
    VisualSpec,
)
from app.infrastructure.ai.mentor_courseware_adapters import ComponentSceneMediaRenderer
from app.infrastructure.persistence.mentor_courseware_store import (
    InMemoryCoursewareRepository,
    InMemoryProductionStatusStore,
)


class _ApiVerifier(ProblemVerificationPort):
    def solve_and_verify(self, *, prompt_text, attachment_keys, guardian_id):
        return VerificationBaseline.create(confidence="high", summary_answer="2√13", stem_text=prompt_text, final_answers=["2√13"])

    def reverify_revision(self, *, baseline, instruction, draft_steps):
        return True, baseline, "ok"


class _ApiDirector(PedagogicalDirectorPort):
    def draft_initial(self, *, prompt_text, baseline, target_grade_hint=None):
        return DirectorDraftResult(
            change_summary="初版",
            methodology_key="化折为直",
            steps=(
                CoursewareStep(
                    step_id="s1",
                    title="对称转化",
                    thinking_why="同侧折线难以直接求最值",
                    action_what="作 A 关于 x 轴对称点 A'(1,-2)",
                    visual_spec=VisualSpec(
                        kind="component_scene",
                        payload={"component": "coord_plane_2d", "points": [{"id": "A", "x": 1, "y": 2}]},
                        static_fallback_text="A(1,2) 对称得 A'(1,-2)",
                    ),
                ),
            ),
        )

    def draft_revision(self, *, current_version, baseline, instruction, target_step_id=None, critique=None):
        return DirectorDraftResult(
            change_summary="已修订",
            methodology_key=current_version.methodology_key,
            steps=(
                CoursewareStep(
                    step_id="s1",
                    title="对称转化（修订）",
                    thinking_why="同侧折线难以直接求最值",
                    action_what=f"修订：{instruction}",
                ),
            ),
            target_step_ids=("s1",),
        )


class _ApiJudge(PedagogicalJudgePort):
    def review(self, *, prompt_text, baseline, draft):
        return PedagogicalJudgeResult(passed=True)


def _make_client(active_guardian: list[UUID]):
    repo = InMemoryCoursewareRepository()
    status_store = InMemoryProductionStatusStore()
    cmds = MentorCoursewareCommandService(repo)
    queries = MentorCoursewareQueryService(repo, status_store)
    orch = MentorCoursewareOrchestrator(
        repo=repo,
        commands=cmds,
        status_store=status_store,
        verifier=_ApiVerifier(),
        director=_ApiDirector(),
        judge=_ApiJudge(),
        renderer=ComponentSceneMediaRenderer(),
    )

    app = FastAPI()
    app.include_router(gc_api.router)
    app.dependency_overrides[current_guardian] = lambda: Principal(user_id=str(active_guardian[0]), role="guardian")
    app.dependency_overrides[gc_api.get_courseware_services] = lambda: (cmds, queries, orch)
    return TestClient(app)


def test_guardian_courseware_api_end_to_end_and_auth_isolation():
    g1, g2 = uuid4(), uuid4()
    active = [g1]
    client = _make_client(active)

    # Create courseware (BackgroundTasks runs synchronously inside TestClient)
    resp = client.post(
        "/guardian/courseware",
        json={"command_id": "create-1", "prompt_text": "将军饮马最短路径"},
    )
    assert resp.status_code == 202
    cid = resp.json()["courseware_id"]

    # Get view -> ready v1
    view = client.get(f"/guardian/courseware/{cid}")
    assert view.status_code == 200
    v1 = view.json()
    assert v1["status"] == "ready"
    assert v1["current_version"]["version_no"] == 1

    # Status endpoint
    st = client.get(f"/guardian/courseware/{cid}/status")
    assert st.status_code == 200
    assert st.json()["stage"] == "ready"

    # Cross-guardian access forbidden (403)
    active[0] = g2
    assert client.get(f"/guardian/courseware/{cid}").status_code == 403
    active[0] = g1

    # Revision -> v2
    rev = client.post(
        f"/guardian/courseware/{cid}/revisions",
        json={
            "command_id": "rev-1",
            "instruction": "补充小马喝水比喻",
            "base_version_no": 1,
            "expected_state_revision": v1["state_revision"],
            "target_step_id": "s1",
        },
    )
    assert rev.status_code == 202
    v2 = client.get(f"/guardian/courseware/{cid}").json()
    assert v2["current_version"]["version_no"] == 2
    assert v2["history_controls"]["can_undo"] is True

    # Undo -> v1
    undo_res = client.post(
        f"/guardian/courseware/{cid}/undo",
        json={"command_id": "undo-1", "expected_state_revision": v2["state_revision"]},
    )
    assert undo_res.status_code == 200
    assert undo_res.json()["current_version"]["version_no"] == 1

    # Redo -> v2
    redo_res = client.post(
        f"/guardian/courseware/{cid}/redo",
        json={"command_id": "redo-1", "expected_state_revision": undo_res.json()["state_revision"]},
    )
    assert redo_res.status_code == 200
    assert redo_res.json()["current_version"]["version_no"] == 2

    # Stale Undo returns 409
    stale = client.post(
        f"/guardian/courseware/{cid}/undo",
        json={"command_id": "undo-stale", "expected_state_revision": 1},
    )
    assert stale.status_code == 409


def test_courseware_baseline_uses_mentor_solver_and_resolved_images(monkeypatch):
    from contextlib import nullcontext

    from app.application.commands.problem_solving import VerifiedSolution
    from app.contexts.problem_solving.domain.dossier import StructuredStem
    from app.infrastructure.ai import mentor_courseware_adapters as adapters

    owner = uuid4()
    image_key = f"guardian/{owner}/experience/diagram.png"

    def resolve_image(guardian, key):
        assert (guardian, key) == (str(owner), image_key)
        return "data:image/png;base64,AA=="

    def solve(*, content, images, solver, bank_lookup):
        assert content == "最短路径" and images == ["data:image/png;base64,AA=="]
        return VerifiedSolution(
            stem=StructuredStem(subject="math", raw_text=content), tier="T1",
            status="ready", confidence="high", final_answers={"1": "√5"},
        )

    monkeypatch.setattr(adapters, "_image", resolve_image)
    monkeypatch.setattr(adapters, "_solve_for_mentor", solve)
    monkeypatch.setattr(adapters, "pin_release", nullcontext)
    baseline = adapters.ProblemSolvingAclAdapter().solve_and_verify(
        prompt_text="最短路径", attachment_keys=(image_key,), guardian_id=owner,
    )
    assert baseline.confidence == "high" and baseline.summary_answer == "√5"
