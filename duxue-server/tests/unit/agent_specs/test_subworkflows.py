import json
from pathlib import Path

import pytest

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.definitions import use_definitions
from app.agent_specs.execution_trace import Recorder
from app.agent_specs.subworkflows import RETRY_NODE, VET_MATH_NODE, VET_NODE
from scripts.upgrade_workflow_nodes import upgrade
from tests.support.fakes import StaticTutorModel
from tests.unit.tutoring.test_leak_retry import HINT, LEAKY, LeaksWhen, _run

SOURCE = Path(__file__).resolve().parents[2] / "fixtures/admin-release.json"


@pytest.fixture
def source():
    return json.loads(SOURCE.read_text())


def test_upgrade_is_compatible_and_repeatable(source):
    original = compile_bundle(source["bundle"])
    upgraded = upgrade(source)
    assert original.digest == source["digest"]
    assert (
        original.catalog.workflow_catalog.spec("tutoring").node(RETRY_NODE).kind
        == "action"
    )
    assert upgrade(upgraded)["digest"] == upgraded["digest"]


@pytest.mark.parametrize("target", ["missing-flow", "tutoring", "tutoring-vet"])
def test_invalid_calls_rejected(source, target):
    bundle = upgrade(source)["bundle"]
    flow = bundle["files"]["workflows/tutoring.json"]
    next(n for n in flow["nodes"] if n["id"] == RETRY_NODE)["ref"] = target
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    with pytest.raises(ValueError):
        compile_bundle(bundle)


@pytest.mark.parametrize("outputs", [[HINT], [LEAKY, HINT]])
def test_attempts_have_separate_review_calls(source, outputs):
    compiled = compile_bundle(upgrade(source)["bundle"])
    recording = Recorder()
    with use_definitions(compiled.catalog), recording.capture():
        result, _ = _run(StaticTutorModel(*outputs), LeaksWhen("等于 4"))
        snapshot = recording.document()
    assert result.vetting.failure is None
    assert set(snapshot["catalog"]["workflows"]) == {
        "tutoring",
        "tutoring-retry",
        "tutoring-vet",
    }
    calls = [event for event in recording.events if event["kind"] == "workflow"]
    assert [event["node_id"] for event in calls] == [RETRY_NODE] + [VET_NODE] * len(
        outputs
    )
    reviews = calls[1:]
    assert len({call["parent_id"] for call in reviews}) == len(outputs)
    for call in reviews:
        assert any(
            e["parent_id"] == call["id"] and e["workflow_id"] == "tutoring-vet"
            for e in recording.events
        )
    assert all(e["duration_ms"] >= 0 for e in calls)
    vet_nodes = {n.id for n in compiled.catalog.workflow_catalog.spec("tutoring-vet").nodes}
    assert VET_MATH_NODE in vet_nodes


def test_indirect_call_cycle_rejected(source):
    bundle = upgrade(source)["bundle"]
    retry = bundle["files"]["workflows/tutoring-retry.json"]
    primary = next(n for n in retry["nodes"] if n["id"] == "tutoring-retry.primary")
    primary.pop("handler_id")
    primary.update(kind="workflow", ref="tutoring")
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    with pytest.raises(ValueError, match="cycle"):
        compile_bundle(bundle)


def test_math_rejection_takes_precedence_in_parallel_vet_workflow(source):
    from scripts.upgrade_math_bundle import upgrade as enable_math
    from tests.unit.math_engine.test_workflow import Judge

    compiled = compile_bundle(upgrade(enable_math(source, enable=True))["bundle"])
    recording = Recorder()
    judge = Judge(False)
    with use_definitions(compiled.catalog), recording.capture():
        result, _ = _run(StaticTutorModel(HINT), judge)
    assert result.vetting.failure == "math_inconsistent"
    # Declarative parallel tutoring-vet workflow runs math_consistency and text_leak
    # concurrently and converges to tutoring-vet.complete with deterministic math precedence.
    assert judge.math_contexts and judge.calls == 2
    assert any(e.get("node_id") == VET_MATH_NODE for e in recording.events)
    assert any(e.get("node_id") == VET_NODE for e in recording.events)


def test_rename_model_loop_preserves_old_release_and_executes_new_trace(source):
    from scripts.rename_model_loop import upgrade as rename

    old = upgrade(source)
    migrated = rename(old)
    assert rename(migrated)["digest"] == migrated["digest"]
    assert compile_bundle(old["bundle"]).digest == old["digest"]
    files = migrated["bundle"]["files"]
    assert "workflows/tutoring-retry.json" not in files
    compiled = compile_bundle(migrated["bundle"])
    graph = compiled.catalog.workflow_catalog
    assert graph.spec("tutoring").node(RETRY_NODE).ref == RETRY_NODE
    assert graph.spec(RETRY_NODE).entry == RETRY_NODE + ".primary"
    trace = Recorder()
    with use_definitions(compiled.catalog), trace.capture():
        result, _ = _run(StaticTutorModel(LEAKY, HINT), LeaksWhen("等于 4"))
    assert result.vetting.failure is None
    assert any(e.get("node_id") == RETRY_NODE + ".repair" for e in trace.events)


def test_named_candidate_review_runs_and_preserves_required_gates(source):
    from scripts.rename_candidate_review import upgrade as rename_review
    from scripts.rename_model_loop import upgrade as rename_loop

    old = rename_loop(upgrade(source))
    new = rename_review(old)
    assert compile_bundle(old["bundle"]).digest == old["digest"]
    assert rename_review(new)["digest"] == new["digest"]
    files = new["bundle"]["files"]
    assert "workflows/tutoring-vet.json" not in files
    compiled = compile_bundle(new["bundle"])
    graph = compiled.catalog.workflow_catalog
    assert graph.spec("tutoring").node(VET_NODE).ref == VET_NODE
    recording = Recorder()
    with use_definitions(compiled.catalog), recording.capture():
        result, _ = _run(StaticTutorModel(LEAKY, HINT), LeaksWhen("等于 4"))
    assert result.vetting.failure is None
    assert any(e.get("workflow_id") == VET_NODE and
               e.get("node_id") == VET_NODE + ".text_leak" for e in recording.events)
    assert graph.component_by_id(VET_NODE, "tutoring.leak-judge").component_id == "tutoring.leak-judge"
    files[f"workflows/{VET_NODE}.json"]["required_gates"] = []
    new["bundle"]["compatibility"] = contract_compatibility(files)
    with pytest.raises(ValueError, match="required Gate baseline"):
        compile_bundle(new["bundle"])
