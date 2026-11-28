import json
from pathlib import Path

import pytest

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.definitions import use_definitions
from app.agent_specs.execution_trace import Recorder
from scripts.upgrade_tutoring_turn import upgrade
from tests.application.study.test_tutoring_workflow_usecase import (
    KNOWLEDGE,
    _ask,
    _setup,
    _workflow,
)


@pytest.fixture
def migrated():
    source = Path(__file__).resolve().parents[2] / "fixtures/admin-release.json"
    return upgrade(json.loads(source.read_text()))


def change_target(bundle, source, target, condition=None):
    flow = bundle["files"]["workflows/tutoring.json"]
    edge = next(
        edge
        for edge in flow["edges"]
        if edge["from"] == "tutoring." + source
        and edge.get("condition_id") == condition
    )
    edge["to"] = target
    bundle["compatibility"] = contract_compatibility(bundle["files"])


@pytest.mark.parametrize(
    "source,target,condition",
    [
        ("model_loop", "tutoring.answer", None),
        ("output_safety", "tutoring.apply_problem", "unsafe_output"),
        ("output_safety", "tutoring.answer", "failed"),
        ("result", "tutoring.result", None),
    ],
)
def test_publication_rejects_unsafe_or_cyclic_paths(
    migrated, source, target, condition
):
    change_target(migrated["bundle"], source, target, condition)
    with pytest.raises(ValueError):
        compile_bundle(migrated["bundle"])


def test_real_entry_uses_changed_release_edge(db, migrated):
    assert upgrade(migrated)["digest"] == migrated["digest"]
    _, session = _setup(db)
    bundle = migrated["bundle"]
    for direct in (False, True):
        if direct:
            change_target(bundle, "answer", "END")
        recording = Recorder()
        with use_definitions(compile_bundle(bundle).catalog), recording.capture():
            workflow, _ = _workflow(db, KNOWLEDGE)
            outcome = _ask(db, workflow, session)
        assert KNOWLEDGE["content"] in outcome.next_interaction["content"]
        visits = [e["node_id"] for e in recording.events if e["kind"] == "action"]
        assert ("tutoring.result" in visits) == (not direct)


def test_rollout_assignment_is_stable_at_boundaries(migrated):
    from uuid import UUID

    from app.agent_specs.tutoring_paths import new_run_version

    spec = compile_bundle(migrated["bundle"]).catalog.workflow_catalog.spec("tutoring")
    cohort = spec.model_copy(update={"rollout_percent": 10})
    assert new_run_version(cohort, str(UUID(int=109))) == "turn_graph"
    assert new_run_version(cohort, str(UUID(int=110))) == "v1"
    assert (
        new_run_version(spec.model_copy(update={"execution": None}), str(UUID(int=0)))
        == "v1"
    )


def test_failed_persistence_rolls_back_and_can_retry(db, migrated, monkeypatch):
    from app.infrastructure.persistence.models import TutoringMessage, TutoringProblem
    from tests.application.study.test_tutoring_workflow_usecase import ATTEMPT

    _, session = _setup(db)
    with use_definitions(compile_bundle(migrated["bundle"]).catalog):
        workflow, _ = _workflow(db, ATTEMPT)
        apply = workflow._apply_problem

        def interrupted(*args, **kwargs):
            apply(*args, **kwargs)
            raise RuntimeError("injected persistence interruption")

        with monkeypatch.context() as fault:
            fault.setattr(workflow, "_apply_problem", interrupted)
            with pytest.raises(RuntimeError, match="injected persistence"):
                _ask(db, workflow, session)
            db.rollback()
        assert (
            db.query(TutoringMessage).count() == db.query(TutoringProblem).count() == 0
        )
        workflow, _ = _workflow(db, ATTEMPT)
        _ask(db, workflow, session)
        assert db.query(TutoringProblem).count() == 1
        assert db.query(TutoringMessage).count() == 2


def test_changing_rollout_only_affects_new_runs(db, migrated):
    from app.application.process_managers.companion_coordinator import (
        CompanionCoordinator,
    )
    from tests.support.factories import create_ward
    from tests.support.fakes import FakeWorkflowDispatcher

    ward = create_ward(db)
    dispatcher = FakeWorkflowDispatcher()
    coordinator = CompanionCoordinator(db, dispatcher=dispatcher)
    params = {"ward_id": ward.id, "content": "看看这道题", "route_hint": "tutoring"}
    bundle = migrated["bundle"]
    with use_definitions(compile_bundle(bundle).catalog):
        first = coordinator.handle(**params, thread_id=None, expected_thread_version=0)
    assert dispatcher.invocations[-1].turn["tutoring_graph_version"] == "v1"
    bundle["files"]["workflows/tutoring.json"]["rollout_percent"] = 100
    with use_definitions(compile_bundle(bundle).catalog):
        coordinator.handle(
            **params,
            thread_id=first.thread_id,
            expected_thread_version=first.thread_version,
        )
        assert dispatcher.invocations[-1].turn["tutoring_graph_version"] == "v1"
        other = create_ward(db)
        coordinator.handle(
            **{**params, "ward_id": other.id}, thread_id=None, expected_thread_version=0
        )
        assert dispatcher.invocations[-1].turn["tutoring_graph_version"] == "turn_graph"


def test_historical_context_node_can_be_bypassed_without_changing_checks(
    db, migrated, monkeypatch
):
    bundle = migrated["bundle"]
    for include_context in (True, False):
        if not include_context:
            change_target(bundle, "image_target", "tutoring.model_loop", "resolved")
        _, session = _setup(db)
        trace = Recorder()
        with use_definitions(compile_bundle(bundle).catalog), trace.capture():
            workflow, model = _workflow(db, KNOWLEDGE)
            _ask(db, workflow, session)
        assert len(model.calls) == 1
        chosen = [
            e["to"]
            for e in trace.events
            if e["kind"] == "edge" and e["workflow_id"] == "tutoring" and e["selected"]
        ]
        assert ("tutoring.self_review" in chosen) == include_context
        assert "tutoring.output_safety" in chosen


def test_migration_preserves_already_published_child_flows(db):
    from scripts.upgrade_workflow_nodes import upgrade as install_children

    source = Path(__file__).resolve().parents[2] / "fixtures/admin-release.json"
    previous = install_children(json.loads(source.read_text()))
    updated = upgrade(previous)
    key = "workflows/tutoring.json"
    assert {k: v for k, v in updated["bundle"]["files"].items() if k != key} == {
        k: v for k, v in previous["bundle"]["files"].items() if k != key
    }
    _, session = _setup(db)
    trace = Recorder()
    with use_definitions(compile_bundle(updated["bundle"]).catalog), trace.capture():
        workflow, _ = _workflow(db, KNOWLEDGE)
        _ask(db, workflow, session)
    assert any(event["workflow_id"] == "tutoring-retry" for event in trace.events)
    assert (
        sum(
            event.get("node_id") == "tutoring.model_loop"
            and event["kind"] == "workflow"
            for event in trace.events
        )
        == 1
    )
