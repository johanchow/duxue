import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.definitions import use_definitions
from app.application.workflows import guardian_mentor
from app.infrastructure.ai import components
from scripts.upgrade_guardian_mentor_review import upgrade
from scripts.upgrade_math_bundle import upgrade as add_guardian


@pytest.fixture(scope="module")
def base_guardian():
    source = json.loads(Path("tests/fixtures/admin-release.json").read_text())
    return add_guardian(source, guardian_mentor=True)


@pytest.fixture(scope="module")
def staged(base_guardian):
    record = upgrade(base_guardian)
    assert upgrade(record)["digest"] == record["digest"]
    return compile_bundle(record["bundle"]).catalog


@pytest.fixture(scope="module")
def simple(base_guardian):
    record = upgrade(base_guardian, simplify=True)
    assert upgrade(record, simplify=True)["digest"] == record["digest"]
    return compile_bundle(record["bundle"]).catalog


@pytest.fixture(scope="module")
def direct(base_guardian):
    staged_rec = upgrade(base_guardian)
    record = upgrade(staged_rec, direct=True)
    assert upgrade(record, direct=True)["digest"] == record["digest"]
    assert "gates/tutoring.mentor-review.json" not in record["bundle"]["files"]
    assert "agents/tutoring.mentor-repair.json" not in record["bundle"]["files"]
    wf = record["bundle"]["files"]["workflows/guardian-mentor.json"]
    assert [n["id"] for n in wf["nodes"]] == ["guardian-mentor.explain"]
    prompt = record["bundle"]["files"]["agents/tutoring.mentor-explain.json"]["prompt"]["template"]
    assert "额外返回 sections" not in prompt
    return compile_bundle(record["bundle"]).catalog


@pytest.mark.parametrize("fixture_name", ["staged", "simple", "direct"])
def test_guardian_mentor_delivers_full_content_without_blocking_review(
    request, fixture_name, monkeypatch
):
    catalog = request.getfixturevalue(fixture_name)
    monkeypatch.setattr(guardian_mentor, "_solve_for_mentor", lambda **kwargs: None)
    calls = []
    long_essay = "Full explanation with complete essay. " * 120  # > 4000 chars

    def provider(*, spec, user, **kwargs):
        calls.append(spec.component_id)
        assert spec.component_id == "tutoring.mentor-explain"
        return {
            "act": "explain",
            "content": long_essay,
            "visual": {"kind": "invalid_kind", "alt": "bad"},
        }

    monkeypatch.setattr(components, "invoke_json_component", provider)
    with use_definitions(catalog):
        response = guardian_mentor.explain_for_guardian(
            guardian_id=str(uuid4()),
            content="应用文写作",
            attachment_keys=[],
            window=[],
            images=[],
            rows=[],
        )
    assert calls == ["tutoring.mentor-explain"]
    assert response["act"] == "explain"
    assert long_essay in response["content"]
    assert "核验状态说明" in response["content"]
    assert "visual" not in response


def test_duplicate_keys_in_keyed_review_are_rejected(simple):
    wire = '{"1":{"id":"1","status":"wrong","reason":""},"1":{"id":"1","status":"pass","reason":""}}'
    completion = components.ChatCompletionResult(
        raw=wire, finish_reason="stop", stream_completed=True
    )
    with (
        use_definitions(simple),
        pytest.raises(components._CompletionClassifiedError, match="json_parse_error"),
    ):
        components.validate_json_completion(
            completion, unit_id="tutoring.mentor-review"
        )
