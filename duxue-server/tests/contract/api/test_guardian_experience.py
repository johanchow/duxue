import json
from unittest.mock import patch

import pytest

from app.infrastructure.persistence.models import Guardian, User, uid
from app.infrastructure.security.experience_tokens import seal, unseal
from app.infrastructure.security.tokens import create_access_token

BASE = "/guardian/experience"
FLOW = "app.application.workflows.guardian_experience"


@pytest.fixture
def adult(db):
    identifier = uid()
    db.add(User(id=identifier, type="guardian"))
    db.flush()
    db.add(Guardian(id=identifier, name="Parent", email="parent@example.com", role="guardian"))
    db.commit()
    return identifier, {"Authorization": f"Bearer {create_access_token(user_id=identifier, role='guardian')}"}


@pytest.fixture
def model():
    with patch(f"{FLOW}.QwenTutorTurnGateway") as gateway, patch(f"{FLOW}.QwenLeakJudge") as judge:
        gateway.return_value.complete.return_value = {
            "act": "guide", "content": "先想想怎样把分母变成相同的数？",
            "turn": {"type": "work", "relation": "new", "depth": "reasoning"},
        }
        judge.return_value.check_math.return_value = True
        judge.return_value.leaks.return_value = {"leaks": False, "answer_protected": True, "reason": None}
        judge.return_value.visual_leaks.return_value = False
        yield gateway.return_value, judge.return_value


def test_adult_without_children_uses_checked_tutoring_without_any_business_writes(client, db, adult, model):
    from app.infrastructure.persistence.database import Base
    before = {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables}
    response = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "比较3/4与2/3，给我提示"})
    assert response.status_code == 200, response.text
    assert response.json()["content"] == "先想想怎样把分母变成相同的数？"
    state = unseal(response.json()["state_token"], adult[0], "conversation")
    assert state["problem"]["disclosure"] == "protected"
    assert state["problem"]["hints_given"] == 1
    assert len(state["window"]) == 2
    assert {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables} == before


def test_multi_turn_keeps_protection_and_only_the_signed_adult_window(client, adult, model):
    first = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "比较3/4与2/3"}).json()
    model[0].complete.return_value["turn"]["relation"] = "same"
    second = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "我不知道怎么通分", "state_token": first["state_token"]})
    assert second.status_code == 200, second.text
    call = model[0].complete.call_args.kwargs
    assert json.loads(call["instruction"])["permit"]["answer_protected"] is True
    assert call["envelope"]["actor"] == {"role": "guardian", "experience": True}
    assert call["envelope"]["memory"] == []
    assert any(row["text"] == "比较3/4与2/3" for row in call["recent_utterances"])


@pytest.mark.parametrize("body", [{}, {"content": " "}, {"content": "hi", "ward_id": "child"},
                                  {"content": "hi", "history": []}])
def test_rejects_empty_input_and_client_injected_ward_or_history(client, adult, body):
    assert client.post(f"{BASE}/turn", headers=adult[1], json=body).status_code == 422


def test_tokens_are_account_purpose_expiry_and_signature_bound(client, adult):
    for token in [seal("other", "conversation", {}), seal(adult[0], "speech", {}),
                  seal(adult[0], "conversation", {}) + "x", "not-a-token"]:
        assert client.post(f"{BASE}/turn", headers=adult[1], json={"content": "hi", "state_token": token}).status_code == 409
    with patch("app.infrastructure.security.experience_tokens.time.time", return_value=0):
        token = seal(adult[0], "conversation", {})
    assert client.post(f"{BASE}/turn", headers=adult[1], json={"content": "hi", "state_token": token}).status_code == 409


def test_all_experience_endpoints_require_adult_auth(client, adult):
    for path, body in [("turn", {"content": "hi"}), ("attachments/upload-url", {"extension": "jpg", "content_type": "image/jpeg"}),
                       ("speech", {"speech_ref": "x"})]:
        assert client.post(f"{BASE}/{path}", json=body).status_code == 401
        headers = {"Authorization": f"Bearer {create_access_token(user_id=adult[0], role='ward')}"}
        assert client.post(f"{BASE}/{path}", headers=headers, json=body).status_code == 401


@pytest.mark.parametrize("key", ["ward/child/companion/a.jpg", "guardian/other/experience/a.jpg", "../a.jpg"])
def test_images_cannot_cross_guardians_or_read_child_media(client, adult, key):
    assert client.post(f"{BASE}/turn", headers=adult[1], json={"attachment_keys": [key]}).status_code == 400


def test_uploaded_images_use_guardian_namespace_and_reject_mime_mismatch(client, adult):
    with patch("app.api.v1.guardian_experience.storage.upload_url", return_value=("https://upload", 9999999999, {})):
        result = client.post(f"{BASE}/attachments/upload-url", headers=adult[1], json={"extension": "png", "content_type": "image/png"})
    assert result.status_code == 200
    assert result.json()["oss_key"].startswith(f"guardian/{adult[0]}/experience/")
    assert client.post(f"{BASE}/attachments/upload-url", headers=adult[1], json={"extension": "jpg", "content_type": "image/png"}).status_code == 400


def test_approved_image_reaches_model_and_independent_judge(client, adult, model):
    from app.application.workflows.tutor_loop import ModelCall, TurnResult, Vetting
    from app.application.workflows.tutor_turn import TutorTurnCandidate
    candidate = TutorTurnCandidate.model_validate(model[0].complete.return_value)
    result = TurnResult(ModelCall(candidate), Vetting(candidate, None))
    key = f"guardian/{adult[0]}/experience/a.png"
    with patch("app.api.v1.guardian_experience.storage.exists", return_value=True), patch(f"{FLOW}.storage.read_bytes", return_value=b"image"), patch(f"{FLOW}.run_tutor_turn", return_value=result) as run:
        result = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "请给一个提示", "attachment_keys": [key]})
    assert result.status_code == 200, result.text
    assert run.call_args.args[4][0].startswith("data:image/png;base64,")
    assert run.call_args.kwargs["judge_images"] == run.call_args.args[4]


def test_judge_failure_never_shows_rejected_draft_or_advances_problem(client, adult, model):
    model[1].leaks.return_value = None
    response = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "比较分数"})
    assert response.status_code == 200
    assert response.json()["act"] == "unavailable"
    assert "先想想" not in response.json()["content"]
    assert unseal(response.json()["state_token"], adult[0], "conversation")["problem"] is None


def test_checked_diagram_is_returned_and_pronunciation_has_its_own_scoped_token(client, adult, model):
    diagram = {"kind": "steps", "alt": "比较分数的两个步骤", "steps": [{"label": "通分"}, {"label": "比较"}]}
    model[0].complete.return_value["visual"] = diagram
    response = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "怎么比较两个分数？"})
    assert response.status_code == 200, response.text
    assert response.json()["visual"]["steps"][0]["label"] == "通分"
    model[0].complete.return_value = {
        "act": "pronounce", "content": "听听这个词怎么读。", "pronounce": {"lesson": {
            "source_text": "apple", "locale": "en-US", "introduction": "读一读", "reading_guide": "注意第一个音节。",
        }},
    }
    response = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "apple怎么读？"})
    assert response.status_code == 200, response.text
    lesson = response.json()["lessons"][0]
    assert unseal(lesson["speech_ref"], adult[0], "speech")["source_text"] == "apple"
    with pytest.raises(ValueError):
        unseal(lesson["speech_ref"], adult[0], "conversation")


def test_speech_only_uses_server_approved_lesson_and_supported_rate(client, adult):
    ref = seal(adult[0], "speech", {"source_text": "apple", "locale": "en-US"})
    with patch("app.api.v1.guardian_experience.AliyunSpeechSynthesizer") as synth:
        synth.return_value.synthesize.return_value = b"mp3"
        result = client.post(f"{BASE}/speech", headers=adult[1], json={"speech_ref": ref, "rate": 0.75})
        assert result.content == b"mp3"
        synth.return_value.synthesize.assert_called_once_with(text="apple", locale="en-US", rate=0.75)
    assert client.post(f"{BASE}/speech", headers=adult[1], json={"speech_ref": ref, "rate": 2}).status_code == 400
    assert client.post(f"{BASE}/speech", headers=adult[1], json={"speech_ref": ref, "source_text": "injected"}).status_code == 422
