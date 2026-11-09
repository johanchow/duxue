"""Named instructions and static tools are validated data, never executable config."""

import json
import shutil

import pytest
from pydantic import ValidationError

from app.agent_specs.definitions import (
    ROOT,
    DefinitionCatalog,
    PromptDefinition,
    ToolDefinition,
)


def fragment(template="只修正 {{reason}}。"):
    return {"id": "test.repair.v1", "template": template,
            "variables": {"reason": {"type": "string", "binding": "context.reason"}}}


def test_named_fragment_renders_once_and_checks_variables():
    from app.infrastructure.ai.prompts import render_fragment

    assert render_fragment("tutoring.turn", "invalid_json") == (
        "返回的内容不是有效 JSON 对象；只返回一个符合 tutor-turn.v4 的 JSON 对象。"
    )
    value = render_fragment("tutoring.turn", "visual_schema", reason="{{draft}}", draft="草稿")
    assert "（{{draft}}）" in value  # inserted text is never interpreted again
    with pytest.raises(ValueError):
        render_fragment("tutoring.turn", "visual_schema", reason="缺少草稿")
    with pytest.raises(ValueError):
        render_fragment("tutoring.turn", "visual_schema", reason=[], draft="草稿")
    with pytest.raises(KeyError):
        render_fragment("tutoring.turn", "unknown")


def test_fragments_accept_explicit_variables_but_reject_expressions_and_mismatches():
    prompt = PromptDefinition.model_validate({
        "id": "test.system.v1", "template": "主模板", "fragments": {"repair": fragment()},
    })
    assert prompt.fragments["repair"].variables["reason"]["type"] == "string"
    with pytest.raises(ValidationError):
        PromptDefinition.model_validate({"id": "test.v1", "template": "主模板",
                                         "fragments": {"repair": {**fragment(), "when": "eval(user)"}}})
    with pytest.raises(ValidationError):
        PromptDefinition.model_validate({"id": "test.v1", "template": "主模板",
                                         "fragments": {"repair": fragment("{{missing}}")}})


def tool(**changes):
    return {"id": "test.static", "version": "v1", "kind": "tool", "description": "规范",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "output_schema": {"type": "object", "properties": {"text": {"type": "string"}},
                              "required": ["text"], "additionalProperties": False},
            "handler_id": "tool.static_result", "access": "read", "static_result": {"text": "正文"},
            **changes}


@pytest.mark.parametrize("changes", [
    {"access": "write"}, {"static_result": None}, {"static_result": {"text": 3}},
    {"handler_id": "tutoring.lookup_history"},
])
def test_static_tool_rejects_write_missing_or_invalid_result(changes):
    with pytest.raises(ValueError):
        ToolDefinition.model_validate(tool(**changes))


def test_static_tool_accepts_valid_result_and_legacy_handler_needs_no_result():
    assert ToolDefinition.model_validate(tool()).static_result == {"text": "正文"}
    legacy = tool(handler_id="tutoring.lookup_history")
    del legacy["static_result"]
    assert ToolDefinition.model_validate(legacy).static_result is None


def test_static_tool_runtime_returns_validated_independent_results():
    from app.agent_specs.static_tools import static_tool_result

    first = static_tool_result("tutoring.widget_guidelines")
    assert first["status"] == "unique" and "SVG Visualizer" in first["guidelines"]
    first["guidelines"] = "篡改"
    assert "SVG Visualizer" in static_tool_result("tutoring.widget_guidelines")["guidelines"]
    with pytest.raises(ValueError):
        static_tool_result("tutoring.lookup_history")
    with pytest.raises(ValueError):
        static_tool_result("tutoring.widget_guidelines", {"unexpected": True})


def test_definition_digest_covers_fragment_and_static_tool_content(tmp_path):
    shutil.copytree(ROOT, tmp_path / "specs")
    root = tmp_path / "specs"
    before = DefinitionCatalog(root).definition_digest("tutoring.turn")
    path = root / "agents/tutoring.turn.json"
    data = json.loads(path.read_text())
    data["prompt"]["fragments"]["invalid_json"]["template"] += "新版本"
    path.write_text(json.dumps(data))
    after_fragment = DefinitionCatalog(root).definition_digest("tutoring.turn")
    assert before != after_fragment
    path = root / "tools/tutoring.widget_guidelines.json"
    data = json.loads(path.read_text())
    data["static_result"]["guidelines"] += "新版本"
    path.write_text(json.dumps(data))
    assert DefinitionCatalog(root).definition_digest("tutoring.turn") != after_fragment


def test_catalog_rejects_fragment_id_colliding_with_another_prompt(tmp_path):
    shutil.copytree(ROOT, tmp_path / "specs")
    root = tmp_path / "specs"
    path = root / "agents/tutoring.turn.json"
    data = json.loads(path.read_text())
    data["prompt"]["fragments"]["invalid_json"]["id"] = "planning.intake.prompt.v6"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="duplicate Prompt ID"):
        DefinitionCatalog(root)


def test_show_exposes_fragment_definitions_static_content_and_digest():
    from app.agent_specs.catalog import load_catalog

    details = load_catalog().expanded("tutoring")["component_details"]
    turn = next(row for row in details if row["id"] == "tutoring.turn")
    assert turn["prompt_fragments"]["visual_schema"]["variables"]["draft"]["type"] == "string"
    assert "SVG Visualizer" in turn["tools"]["tutoring.widget_guidelines"]["static_result"]["guidelines"]
    assert len(turn["definition_digest"]) == 64
