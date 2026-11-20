import json
from pathlib import Path

import pytest

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.definitions import use_definitions
from app.agent_specs.execution_trace import Recorder
from app.agent_specs.subworkflows import MATH_NODE, RETRY_NODE, VET_NODE
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
    assert len([e for e in recording.events if e.get("node_id") == MATH_NODE]) == len(
        outputs
    )
    assert all(e["duration_ms"] >= 0 for e in calls)


def test_indirect_call_cycle_rejected(source):
    bundle = upgrade(source)["bundle"]
    retry = bundle["files"]["workflows/tutoring-retry.json"]
    primary = next(n for n in retry["nodes"] if n["id"] == "tutoring-retry.primary")
    primary.pop("handler_id")
    primary.update(kind="workflow", ref="tutoring")
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    with pytest.raises(ValueError, match="cycle"):
        compile_bundle(bundle)


def test_math_rejection_stops_before_teaching_review(source):
    from scripts.upgrade_math_bundle import upgrade as enable_math
    from tests.unit.math_engine.test_workflow import Judge

    compiled = compile_bundle(upgrade(enable_math(source, enable=True))["bundle"])
    recording = Recorder()
    judge = Judge(False)
    with use_definitions(compiled.catalog), recording.capture():
        result, _ = _run(StaticTutorModel(HINT), judge)
    assert result.vetting.failure == "math_inconsistent"
    assert judge.math_contexts and not judge.calls
    assert any(e.get("node_id") == MATH_NODE for e in recording.events)
    assert not any(e.get("node_id") == VET_NODE for e in recording.events)
