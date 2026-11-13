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
        "behavior-observation.prepare",
        "behavior-observation.activity",
        "behavior-observation.validate-activity",
    ]
    assert "SECRET" not in str(trace.events)


@pytest.mark.parametrize(
    "identifier",
    [
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
            "behavior-observation", DebugInput(content='{"synthetic":true}')
        )
    assert result["eligible"] is False
    assert len([e for e in trace.events if e.get("kind") == "agent"]) == 5
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
    graph = bundle["files"]["workflows/behavior-observation.json"]
    graph["nodes"].pop()
    graph["edges"][-2]["to"] = "END"
    graph["edges"].pop()
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    with pytest.raises(ValueError):
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
                "target_id": "behavior-observation",
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


def test_business_workflow_eligible_branch_reaches_shadow_delivery(observation_release):
    import json
    from datetime import datetime

    from app.agent_specs.observation_debug import run_business_debug

    def window(index):
        start = T + timedelta(minutes=index)
        frames = [
            {
                "id": f"frame-{index}-{n}",
                "at": (start + timedelta(seconds=n * 15)).isoformat(),
            }
            for n in range(4)
        ]
        manifest = {
            "ward_id": "ward",
            "camera_id": "camera",
            "assignment_revision": 1,
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=1)).isoformat(),
            "frames": frames,
        }
        cells = [
            {
                "start": f["at"],
                "end": (
                    datetime.fromisoformat(f["at"]) + timedelta(seconds=15)
                ).isoformat(),
                "activity": "still_with_material",
                "evidence_frame_ids": [f["id"]],
            }
            for f in frames
        ]
        return {"manifest": manifest, "result": {"cells": cells}}

    current = window(3)

    class Vision(ObservationVision):
        def prepare(self, payload, *, limit):
            return [{"type": "text", "text": json.dumps(payload)}]

        def invoke_model(self, identifier, parts):
            if identifier == "behavior.visible-activity":
                return current["result"]
            return {
                "decision": "offer_help",
                "evidence_refs": [current["manifest"]["frames"][-1]["id"]],
                "observed_basis": "visible stillness",
                "uncertainty_reason": None,
            }

    trace = Recorder()
    with (
        patch(
            "app.agent_specs.observation_debug.debug_vision",
            return_value=(Vision(), current["manifest"]),
        ),
        trace.capture(),
    ):
        result = run_business_debug(
            {"prior_windows": [window(n) for n in range(3)]}, None
        )
    assert result["eligible"] is True
    assert result["invitation"]["offers"] == [
        {"kind": "offer_help", "status": "shadow"}
    ]
    assert result["invitation"]["presentation"] is None
    nodes = [e["node_id"] for e in trace.events if e.get("kind") == "agent"]
    assert nodes == [
        "behavior-observation." + n
        for n in [
            "prepare",
            "activity",
            "validate-activity",
            "aggregate",
            "eligibility",
            "support-images",
            "support",
            "validate-support",
            "invitation",
            "delivery",
        ]
    ]


def test_only_business_and_report_workflows_are_exposed(observation_release):
    names = set(observation_release.catalog.workflow_catalog.specs)
    assert {name for name in names if name.startswith("behavior-")} == {
        "behavior-observation",
        "behavior-report",
    }
