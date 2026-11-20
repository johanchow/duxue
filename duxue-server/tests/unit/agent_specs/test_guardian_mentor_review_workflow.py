import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.definitions import use_definitions
from app.application.workflows import guardian_mentor
from app.infrastructure.ai import components
from app.infrastructure.ai.components import invoke_json_component
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
    bundle = staged_rec["bundle"]
    mentor = bundle["files"]["agents/tutoring.mentor-explain.json"]
    mentor["output_contract"] = "tutoring.mentor-explain.output.v1"
    mentor["output_schema"]["properties"]["content"]["maxLength"] = 3600
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    staged_rec["digest"] = compile_bundle(bundle).digest
    record = upgrade(staged_rec, direct=True)
    assert upgrade(record, direct=True)["digest"] == record["digest"]
    assert "gates/tutoring.mentor-review.json" not in record["bundle"]["files"]
    assert "agents/tutoring.mentor-repair.json" not in record["bundle"]["files"]
    wf = record["bundle"]["files"]["workflows/guardian-mentor.json"]
    assert [n["id"] for n in wf["nodes"]] == ["guardian-mentor.explain"]
    prompt = record["bundle"]["files"]["agents/tutoring.mentor-explain.json"]["prompt"]["template"]
    assert "额外返回 sections" not in prompt
    return compile_bundle(record["bundle"]).catalog


@pytest.mark.parametrize(
    ("length", "expected"),
    [(4204, "explain"), (8000, "explain"), (8001, "unavailable")],
)
def test_direct_mentor_applies_same_content_limit_at_both_validation_layers(
    direct, monkeypatch, length, expected
):
    from app.infrastructure.ai import client

    content = "解" * length
    completion = components.ChatCompletionResult(
        raw=json.dumps({"act": "explain", "content": content}, ensure_ascii=False),
        finish_reason="stop",
        stream_completed=True,
    )
    complete_chat = Mock(return_value=completion)
    monkeypatch.setattr(client, "dashscope_client", lambda **kwargs: object())
    monkeypatch.setattr(components, "complete_json_chat", complete_chat)
    monkeypatch.setattr(components, "invoke_json_component", invoke_json_component)
    monkeypatch.setattr(guardian_mentor, "_solve_for_mentor", lambda **kwargs: None)
    with use_definitions(direct):
        response = guardian_mentor.explain_for_guardian(
            guardian_id=str(uuid4()),
            content="请解答第21题的全部小问",
            attachment_keys=[],
            window=[],
            images=[],
            rows=[],
            model_settings=SimpleNamespace(),
        )
    assert complete_chat.call_count == (1 if expected == "explain" else 2)
    assert response["act"] == expected
    if expected == "explain":
        assert response["content"].endswith(content)


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


def test_direct_guardian_mentor_retries_concisely_on_truncated_candidate(
    direct, monkeypatch
):
    from app.infrastructure.ai.errors import ModelGatewayError

    monkeypatch.setattr(guardian_mentor, "_solve_for_mentor", lambda **kwargs: None)
    seen_users = []

    def provider(*, spec, user, **kwargs):
        seen_users.append(user)
        if len(seen_users) == 1:
            raise ModelGatewayError("invalid_model_candidate")
        return {"act": "explain", "content": "（1）精简完整解答；（2）核心推导与结论。"}

    monkeypatch.setattr(components, "invoke_json_component", provider)
    with use_definitions(direct):
        response = guardian_mentor.explain_for_guardian(
            guardian_id=str(uuid4()),
            content="请解答第21题",
            attachment_keys=[],
            window=[],
            images=[],
            rows=[],
        )
    assert len(seen_users) == 2
    assert "截断" in str(seen_users[1])
    assert response["act"] == "explain"
    assert "精简完整解答" in response["content"]
