import copy
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.debug_contracts import DebugInput, resolve_target
from app.agent_specs.execution_trace import Recorder
from app.agent_specs.observation_debug import run_observation_debug
from app.infrastructure.ai.behavior_observation import ObservationVision
from tests.unit.behavior.test_observation import T


def test_production_vision_executes_configured_code_llm_code_without_image_trace(
    observation_release,
):
    payload = {
        "ward_id": "ward",
        "camera_id": "camera",
        "assignment_revision": 1,
        "start": T.isoformat(),
        "end": (T + timedelta(minutes=1)).isoformat(),
        "frames": [{"id": "frame", "at": T.isoformat()}],
    }
    result = {
        "cells": [
            {
                "start": T.isoformat(),
                "end": (T + timedelta(seconds=15)).isoformat(),
                "activity": "writing",
                "evidence_frame_ids": ["frame"],
            }
        ],
        "provenance": {"model": "fixture"},
    }
    trace = Recorder()
    with (
        patch.object(
            ObservationVision,
            "prepare",
            return_value=[
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64,SECRET"},
                }
            ],
        ),
        patch.object(ObservationVision, "invoke_model", return_value=result),
        trace.capture(),
    ):
        assert ObservationVision()(payload) == result
    nodes = [e["node_id"] for e in trace.events if e.get("kind") == "agent"]
    assert nodes == [
        "behavior-visible-activity.0",
        "behavior-visible-activity.1",
        "behavior-visible-activity.2",
    ]
    assert "SECRET" not in str(trace.events)


@pytest.mark.parametrize(
    "identifier",
    [
        "behavior-aggregate",
        "behavior-invitation",
        "behavior-report",
        "behavior.aggregate",
        "behavior.invitation",
        "behavior.report",
    ],
)
def test_code_workflow_and_agent_debug_is_isolated(identifier, observation_release):
    data = DebugInput(
        content="{}",
        target_kind="agent" if "." in identifier else "workflow",
        target_id=identifier,
    )
    resolve_target(data, observation_release.catalog)
    trace = Recorder()
    with trace.capture():
        result = run_observation_debug(identifier, data)
    assert result["sandbox"] is True
    assert any(e.get("kind") == "agent" for e in trace.events)


def test_admin_cannot_replace_reviewed_code_handler(observation_release):
    bundle = copy.deepcopy(observation_release.bundle)
    bundle["files"]["agents/behavior.aggregate.json"]["handler_id"] = "os.system"
    with pytest.raises(ValueError):
        compile_bundle(bundle)


def test_upgrade_keeps_prompts_and_source_identity(observation_release):
    from scripts.extend_observation_release import upgrade

    record = {
        "id": "release1",
        "kind": "release",
        "environment": "test",
        "bundle": observation_release.bundle,
        "digest": observation_release.digest,
    }
    upgraded = upgrade(record)
    assert upgraded["migration_source"]["id"] == "release1"
    assert upgraded["migration_source"]["kind"] == "release"
    assert (
        upgraded["bundle"]["files"]["agents/behavior.visible-activity.json"]["prompt"]
        == record["bundle"]["files"]["agents/behavior.visible-activity.json"]["prompt"]
    )
    compile_bundle(upgraded["bundle"])


def test_synthetic_debug_uses_real_workflow_and_no_source_database(observation_release):
    trace = Recorder()
    with (
        patch.object(
            ObservationVision,
            "invoke_model",
            return_value={"cells": [], "provenance": {"model": "fixture"}},
        ),
        trace.capture(),
    ):
        result = run_observation_debug(
            "behavior-visible-activity", DebugInput(content='{"synthetic":true}')
        )
    assert result["cells"] == []
    assert len([e for e in trace.events if e.get("kind") == "agent"]) == 3
    assert "base64," not in str(trace.events)


def test_configured_workflow_node_identity_is_used_at_runtime(observation_release):
    from app.agent_specs.admin_bundle import contract_compatibility
    from app.agent_specs.definitions import use_definitions
    from app.agent_specs.observation_debug import run_observation_debug

    bundle = copy.deepcopy(observation_release.bundle)
    graph = bundle["files"]["workflows/behavior-report.json"]
    graph["entry"] = graph["nodes"][0]["id"] = "behavior-report.configured-node"
    graph["edges"] = [
        {"from": "START", "to": graph["entry"]},
        {"from": graph["entry"], "to": "END"},
    ]
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    compiled = compile_bundle(bundle)
    trace = Recorder()
    with use_definitions(compiled.catalog), trace.capture():
        run_observation_debug("behavior-report", DebugInput(content="{}"))
    assert any(
        e.get("node_id") == "behavior-report.configured-node" for e in trace.events
    )


def test_configuration_cannot_skip_evidence_validation(observation_release):
    from app.agent_specs.admin_bundle import contract_compatibility

    bundle = copy.deepcopy(observation_release.bundle)
    graph = bundle["files"]["workflows/behavior-visible-activity.json"]
    graph["nodes"].pop()
    graph["edges"][-2]["to"] = "END"
    graph["edges"].pop()
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    with pytest.raises(ValueError, match="protocol"):
        compile_bundle(bundle)


def test_debug_worker_propagates_explicit_model_runtime(
    monkeypatch, observation_release
):
    from app.agent_specs.debug_worker import execute
    from app.infrastructure.ai import components

    def model(**kwargs):
        assert kwargs["settings_obj"].agent_model_enabled is True
        return {"cells": []}

    monkeypatch.setattr(components, "invoke_json_component", model)
    result = execute(
        {
            "bundle": observation_release.bundle,
            "input": {
                "target_kind": "workflow",
                "target_id": "behavior-visible-activity",
                "content": '{"synthetic":true}',
            },
        }
    )
    assert result["status"] == "succeeded"
    assert result["covered_components"] == ["behavior.visible-activity"]
    assert result["model_requests"] == 1


@pytest.mark.parametrize(
    "identifier",
    ["behavior.evidence", "behavior.validate-activity", "behavior.validate-support"],
)
def test_independent_code_debug_without_llm(identifier, observation_release):
    import json

    manifest = {
        "ward_id": "ward",
        "camera_id": "camera",
        "assignment_revision": 1,
        "start": T.isoformat(),
        "end": (T + timedelta(minutes=1)).isoformat(),
        "frames": [{"id": "frame", "at": T.isoformat()}],
        "learning_context": {"observed_learning": False},
    }
    response = (
        {"cells": []}
        if identifier.endswith("activity")
        else {
            "decision": "uncertain",
            "evidence_refs": [],
            "observed_basis": "",
            "uncertainty_reason": "no evidence",
        }
    )
    content = (
        {"synthetic": True}
        if identifier.endswith("evidence")
        else {"manifest": manifest, "result": response}
    )
    data = DebugInput(
        content=json.dumps(content), target_kind="agent", target_id=identifier
    )
    resolve_target(data, observation_release.catalog)
    with patch.object(
        ObservationVision,
        "invoke_model",
        side_effect=AssertionError("code agent called model"),
    ):
        run_observation_debug(identifier, data)
