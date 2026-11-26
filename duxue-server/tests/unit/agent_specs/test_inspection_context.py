import json
from types import SimpleNamespace

from app.agent_specs.contexts import tutor_turn
from app.application.ports.image_inspection import InspectImageRequest


def test_authorized_inspection_schema_reaches_image_model(monkeypatch):
    schema = InspectImageRequest.model_json_schema()
    monkeypatch.setattr(
        "app.agent_specs.definitions.load_definitions",
        lambda: SimpleNamespace(
            units={"tutoring.turn": SimpleNamespace(tools=["tutoring.inspect_image"])},
            tools={"tutoring.inspect_image": SimpleNamespace(input_schema=schema)},
        ),
    )
    parts = tutor_turn(
        envelope={},
        instruction="检查图片",
        current_images=["data:image/jpeg;base64,YQ=="],
    )
    payload = json.loads(parts[0]["text"])
    assert payload["optional_inspect_image_tool"]["args_schema"] == schema
    request = {
        "image_ref": "img_0123456789abcdef01234567",
        "bbox": {"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9},
    }
    from jsonschema import validate

    validate(request, payload["optional_inspect_image_tool"]["args_schema"])
    assert payload["optional_inspect_image_tool"]["tool"] == "inspect_image"


def test_partial_review_upgrade_reaches_composed_prompt_from_inline_legacy_template():
    from copy import deepcopy

    from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
    from app.agent_specs.configuration import snapshot_bundle
    from app.agent_specs.definitions import use_definitions
    from app.infrastructure.ai.prompts import PromptTemplate, compose_system_prompt
    from scripts.upgrade_partial_worksheet_review import upgrade

    bundle = deepcopy(snapshot_bundle())
    for name in (
        "agents/tutoring.turn.json",
        "agents/tutoring.image-target.json",
        "gates/tutoring.leak-judge.json",
    ):
        bundle["files"][name]["prompt"]["template"] += (
            "\n\n[image-review.v1]\nlegacy image rules"
        )
    for name in ("agents/tutoring.turn.json", "gates/tutoring.leak-judge.json"):
        bundle["files"][name]["prompt"].setdefault("fragments", {})["image_review"] = {
            "id": bundle["files"][name]["id"] + ".fragment.image_review",
            "template": "[image-review.v1]\nlegacy fragment",
            "variables": {},
        }
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    source = {
        "id": "test",
        "kind": "draft",
        "revision": 1,
        "bundle": bundle,
        "digest": compile_bundle(bundle).digest,
    }
    updated = upgrade(source)
    assert upgrade(updated)["bundle"] == updated["bundle"]
    assert source["bundle"] == bundle
    assert updated["migration_source"]["revision"] == 1
    compiled = compile_bundle(updated["bundle"])
    with use_definitions(compiled.catalog):
        prompt = updated["bundle"]["files"]["agents/tutoring.turn.json"]["prompt"]
        rendered = compose_system_prompt(
            PromptTemplate("test", prompt["template"]),
            "tutoring.turn",
            ("image_review",),
        )
        assert "[image-review.v1]" not in prompt["template"]
        assert "[partial-worksheet-review.v1]" in rendered.text
        assert "[worksheet-spatial-evidence.v1]" in rendered.text


def test_thinking_effort_controls_do_not_leak_into_model_context():
    envelope = {
        "actor": {"role": "ward", "grade_stage": "primary"},
        "_thinking_effort": "medium",
        "_disable_thinking": False,
        "_thinking_budget": 1024,
    }
    parts = tutor_turn(envelope=envelope, instruction="检查作业")
    context = json.loads(parts[0]["text"])["context"]
    assert context == {"actor": envelope["actor"]}
    assert envelope["_thinking_effort"] == "medium"
