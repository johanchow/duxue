import pytest

from app.agent_specs.education_workspace import Comparison, Lesson, Page
from app.application.workflows import education_workspace as ws
from app.application.workflows.guardian_experience import media_prefix
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_guardian


@pytest.mark.parametrize(
    "kind,skill",
    [
        ("lesson_pack", "edu.lesson_pack"),
        ("grading_report", "edu.worksheet_grading"),
    ],
)
def test_adult_document_lifecycle(client, db, monkeypatch, kind, skill):
    adult = create_guardian(db)
    db.commit()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=adult.id, role="guardian")
    }
    thread = client.post("/v1/conversations", headers=headers, json={}).json()[
        "thread_id"
    ]
    keys = (
        [media_prefix(adult.id) + f"{i}.png" for i in range(2)]
        if kind == "grading_report"
        else []
    )
    solves = []

    def verify(stem):
        solves.append(stem)
        return {"1": "7"} if stem == "3+4" else {}

    def proposal(unit, payload, images=None):
        if unit == "edu.lesson-author":
            return Lesson(
                title="加法",
                teaching_notes=payload["request"],
                variants=["3+4", "图中共有几条线？"],
            )
        if unit == "edu.worksheet-page":
            return Page(
                complete=True,
                questions=[
                    dict(
                        label="1",
                        stem="3+4",
                        student_answer="8",
                        legible=payload["page"] == 1,
                    )
                ],
            )
        assert unit == "edu.answer-compare"
        return Comparison(verdict="incorrect", explanation="3 加 4 得 7，作答为 8。")

    monkeypatch.setattr(ws, "proposal", proposal)
    monkeypatch.setattr(ws, "verify", verify)
    monkeypatch.setattr(ws, "_image", lambda owner, key: key)
    monkeypatch.setattr(
        "app.api.v1.guardian_experience.storage.exists", lambda key: True
    )
    body = dict(
        thread_id=thread,
        command_id="create",
        content="第一次生成",
        mode="guardian_explain",
        attachment_keys=keys,
        skill_hint=skill,
    )
    route = "/v1/agent/turns"
    response = client.post(route, json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["artifact_type"] == kind
    url = "/v1/artifacts/" + response.json()["artifact_id"]
    count = len(solves)
    assert client.post(route, json=body, headers=headers).json() == response.json()
    assert len(solves) == count
    document = client.get(url, headers=headers).json()
    assert document["verification_status"] == "partial_needs_review"
    items = [b for b in document["blocks"] if "status" in b]
    assert items[1]["status"] == "needs_manual_review"
    if keys:
        assert [(b["label"], b["page"]) for b in items] == [("1", 1), ("1", 2)]
        assert items[0]["status"] == "incorrect"
    else:
        assert items[0]["status"] == "verified"

    def command(action, rev, **kwargs):
        return client.post(
            url + "/commands",
            headers=headers,
            json=dict(
                action=action, command_id=action, expected_revision=rev, **kwargs
            ),
        )

    saved = command("save", 1)
    assert saved.status_code == 200
    assert command("save", 1).json() == saved.json()
    assert command("revise", 1, instruction="再出一版").status_code == 409
    assert command("revise", 2, instruction="再出一版").json()["version"] == 2
    assert len(solves) > count
    assert command("undo", 3).json()["version"] == 1
    assert command("redo", 4).json()["version"] == 2
    assert (
        client.delete("/v1/conversations/" + thread, headers=headers).status_code == 204
    )
    assert client.get(url, headers=headers).json()["saved"]
    library = client.get(
        "/v1/artifacts", params={"artifact_type": kind}, headers=headers
    ).json()
    assert [i["artifact_id"] for i in library["items"]] == [
        response.json()["artifact_id"]
    ]


def test_ward_study_control_uses_current_intent_once(client, db, monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4
    from app.application.ports.companion import IntentProposal
    from app.application.process_managers import companion_coordinator as coordinator
    from app.infrastructure.ai.intent_classifier import ModelIntentClassifier
    from tests.support.factories import create_ward

    ward = create_ward(db)
    db.commit()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    }
    thread = client.post("/v1/conversations", headers=headers, json={}).json()[
        "thread_id"
    ]
    invalid = client.post("/v1/agent/turns", headers=headers,
                          json={"content": "测试", "command_id": "invalid-id"})
    assert invalid.status_code == 422
    defs = coordinator.load_definitions()
    units = dict(defs.units)
    intent = units["companion.intent"]
    schema = dict(intent.output_schema)
    schema["properties"] = {**schema["properties"], "study_control": {}}
    schema["required"] = [*schema["required"], "teaching_policy"]
    units["companion.intent"] = intent.model_copy(update={"output_schema": schema})
    monkeypatch.setattr(
        coordinator, "load_definitions", lambda: SimpleNamespace(units=units)
    )
    invalid = client.post("/v1/agent/turns", headers=headers, json={"content":"hello", "command_id":"invalid-id"})
    assert invalid.status_code == 422
    calls = []

    def classify(self, **data):
        calls.append(data["content"])
        return IntentProposal(
            intent="tutoring",
            teaching_policy="standard",
            study_control={
                "action": "sprint_prepare",
                "topic": "数学",
                "target_minutes": 10,
            },
        )

    monkeypatch.setattr(ModelIntentClassifier, "propose", classify)
    url = "/v1/agent/turns"
    prompt = "做十分钟数学挑战"
    result = client.post(
        url,
        headers=headers,
        json=dict(content=prompt, thread_id=thread, expected_thread_version=0),
    )
    assert result.status_code == 200, result.text
    reply = result.json()
    assert reply["interaction"]["sprint"]["status"] == "ready"
    action = reply["interaction"]["actions"][0]
    body = dict(
        content="",
        thread_id=thread,
        expected_thread_version=reply["thread_version"],
        command_id=str(uuid4()),
        structured_command={
            "interaction_id": action["id"],
            "command": "sprint_command",
            "payload": action["payload"],
        },
    )
    started = client.post(url, headers=headers, json=body)
    assert started.status_code == 200, started.text
    assert started.json()["interaction"]["sprint"]["status"] == "active"
    assert calls == [prompt]


def test_verification_gate_rejects_a_claim_without_evidence():
    from app.application.commands.workspace_documents import require_review
    from app.application.agent.gates import GateRunner
    from fastapi import HTTPException

    fabricated = ws.Document(
        "lesson_pack",
        "测试",
        [
            dict(
                kind="variant_question",
                status="verified",
                reference_answers={"main": "model claim"},
                needs_manual_review=False,
            )
        ],
    )
    with pytest.raises(HTTPException):
        require_review(fabricated, "write")

    def timeout(*_):
        raise TimeoutError

    runner = GateRunner({"timeout": timeout})
    for gate in ("timeout", "unregistered"):
        assert not runner.allows({gate}, phase="respond", candidate=fabricated)


def test_adult_courseware_handoff_replays_through_unified_turn(client, db):
    adult = create_guardian(db)
    db.commit()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=adult.id, role="guardian")
    }
    thread = client.post("/v1/conversations", headers=headers, json={}).json()[
        "thread_id"
    ]
    request = {
        "content": "制作勾股定理演示",
        "mode": "guardian_explain",
        "thread_id": thread,
        "command_id": "courseware-editor",
        "skill_hint": "edu.interactive_courseware",
    }
    response = client.post("/v1/agent/turns", json=request, headers=headers)
    assert response.status_code == 200
    assert response.json()["recommend_courseware"] is True
    assert (
        client.post("/v1/agent/turns", json=request, headers=headers).json()
        == response.json()
    )


def test_model_plans_general_search_and_uses_its_result(client, db, monkeypatch):
    from app.agent_specs.education_workspace import SkillChoice
    from app.infrastructure.ai.learning_search import LearningSearch

    adult = create_guardian(db)
    db.commit()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=adult.id, role="guardian")
    }
    thread = client.post("/v1/conversations", headers=headers, json={}).json()[
        "thread_id"
    ]
    calls = []

    def choose(**kwargs):
        results = kwargs.get("tool_results")
        if results:
            assert results[0]["tool_id"] == "web.search"
            assert results[0]["data"]["status"] == "ok"
            return SkillChoice(skill="general", answer="查到了一份彩虹实验的参考资料。")
        return SkillChoice(
            skill="general",
            search={"query": "彩虹课堂实验", "learning_purpose": "查找课堂材料"},
        )

    def search(self, request):
        calls.append(request["query"])
        return {"status": "ok", "sources": [{"title": "彩虹课堂实验"}]}

    monkeypatch.setattr(ws, "choose_skill", choose)
    monkeypatch.setattr(LearningSearch, "search", search)
    reply = client.post(
        "/v1/agent/turns",
        headers=headers,
        json={
            "content": "查找彩虹实验材料",
            "mode": "guardian_explain",
            "thread_id": thread,
            "command_id": "search",
        },
    )
    assert reply.status_code == 200
    assert reply.json()["content"] == "查到了一份彩虹实验的参考资料。"
    assert calls == ["彩虹课堂实验"]


def test_late_gate_approval_cannot_authorize_a_write():
    from threading import Event
    from app.application.agent.gates import GateRunner
    release = Event()
    gate = GateRunner({"late": lambda *_: release.wait(1)}, timeout_seconds=0.01)
    try:
        assert not gate.allows({"late"}, phase="write", candidate=None)
    finally:
        release.set()


def test_adult_composite_turn_delivers_multiple_artifacts_and_courseware(
    client, db, monkeypatch
):
    from app.agent_specs.education_workspace import SkillChoice

    adult = create_guardian(db)
    db.commit()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=adult.id, role="guardian")
    }
    thread = client.post("/v1/conversations", headers=headers, json={}).json()[
        "thread_id"
    ]
    keys = [media_prefix(adult.id) + "page1.png"]
    planner_calls = []
    lesson_inputs = []

    def choose(**kwargs):
        completed = kwargs.get("completed_steps") or []
        planner_calls.append(len(completed))
        if len(completed) == 0:
            return SkillChoice(
                action="run_skill",
                skill="edu.worksheet_grading",
                sub_goal="逐题批改这页数学作业",
            )
        if len(completed) == 1:
            assert completed[0]["skill_id"] == "edu.worksheet_grading"
            assert completed[0]["summary"]["wrong_count"] == 1
            return SkillChoice(
                action="run_skill",
                skill="edu.lesson_pack",
                sub_goal="针对第1题错题出2道同类巩固题",
            )
        if len(completed) == 2:
            assert completed[1]["skill_id"] == "edu.lesson_pack"
            return SkillChoice(
                action="run_skill",
                skill="edu.interactive_courseware",
                sub_goal="为第1题（3+4）制作动态讲题课件",
            )
        return SkillChoice(
            action="finish",
            skill="general",
            finish_reason="all_done",
            answer="已完成批改诊断与2道巩固题，并为你准备好错题动态课件入口。",
        )

    def proposal(unit, payload, images=None):
        if unit == "edu.worksheet-page":
            return Page(
                complete=True,
                questions=[
                    dict(label="1", stem="3+4", student_answer="8", legible=True)
                ],
            )
        if unit == "edu.answer-compare":
            return Comparison(verdict="incorrect", explanation="3 加 4 得 7，作答为 8。")
        assert unit == "edu.lesson-author"
        lesson_inputs.append(payload)
        return Lesson(
            title="加法巩固练习",
            teaching_notes="针对3+4计算失误设计",
            variants=["3+4"],
        )

    monkeypatch.setattr(ws, "choose_skill", choose)
    monkeypatch.setattr(ws, "proposal", proposal)
    monkeypatch.setattr(ws, "verify", lambda stem: {"1": "7"} if stem == "3+4" else {})
    monkeypatch.setattr(ws, "_image", lambda owner, key: key)
    monkeypatch.setattr(
        "app.api.v1.guardian_experience.storage.exists", lambda key: True
    )

    body = {
        "thread_id": thread,
        "command_id": "composite-1",
        "content": "批改这页作业，出同类巩固题，并把错题做成动态课件",
        "mode": "guardian_explain",
        "attachment_keys": keys,
    }
    resp = client.post("/v1/agent/turns", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Reached MAX_SKILLS_PER_TURN=3 after courseware; code stops without extra planner call.
    assert planner_calls == [0, 1, 2]
    assert len(data["artifacts"]) == 2
    assert [a["artifact_type"] for a in data["artifacts"]] == [
        "grading_report",
        "lesson_pack",
    ]
    assert data["recommend_courseware"] is True
    assert "3+4" in data["courseware_prompt"]
    assert "作业批改诊断" in data["content"] and "加法巩固练习" in data["content"]
    # Second skill received structured grading summary from step 1
    assert lesson_inputs[0]["previous"]["completed_steps"][0]["summary"]["wrong_count"] == 1
    # Both artifacts are independently persisted and readable
    for art in data["artifacts"]:
        fetched = client.get("/v1/artifacts/" + art["artifact_id"], headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["artifact_type"] == art["artifact_type"]
    # Idempotent replay returns identical payload without re-running planner
    replay = client.post("/v1/agent/turns", json=body, headers=headers)
    assert replay.json() == data
    assert planner_calls == [0, 1, 2]


def test_adult_composite_early_finish_dedup_and_partial_failure(
    client, db, monkeypatch
):
    from app.agent_specs.education_workspace import SkillChoice
    from app.infrastructure.ai.errors import ModelGatewayError

    adult = create_guardian(db)
    db.commit()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=adult.id, role="guardian")
    }
    thread = client.post("/v1/conversations", headers=headers, json={}).json()[
        "thread_id"
    ]
    keys = [media_prefix(adult.id) + "page1.png"]

    def base_proposal(unit, payload, images=None):
        if unit == "edu.worksheet-page":
            return Page(
                complete=True,
                questions=[dict(label="1", stem="3+4", student_answer="7", legible=True)],
            )
        if unit == "edu.answer-compare":
            return Comparison(verdict="correct", explanation="完全正确。")
        raise ModelGatewayError("model_unavailable")

    monkeypatch.setattr(ws, "proposal", base_proposal)
    monkeypatch.setattr(ws, "verify", lambda stem: {"1": "7"})
    monkeypatch.setattr(ws, "_image", lambda owner, key: key)
    monkeypatch.setattr(
        "app.api.v1.guardian_experience.storage.exists", lambda key: True
    )

    # 1. Early finish when all answers are correct (precondition_unmet)
    def choose_early(**kwargs):
        completed = kwargs.get("completed_steps") or []
        if not completed:
            return SkillChoice(action="run_skill", skill="edu.worksheet_grading")
        assert completed[0]["summary"]["wrong_count"] == 0
        return SkillChoice(
            action="finish",
            skill="general",
            finish_reason="precondition_unmet",
            answer="全部做对，无需额外错题巩固。",
        )

    monkeypatch.setattr(ws, "choose_skill", choose_early)
    r1 = client.post(
        "/v1/agent/turns",
        headers=headers,
        json={
            "thread_id": thread,
            "command_id": "early-finish",
            "content": "批改并出错题巩固",
            "mode": "guardian_explain",
            "attachment_keys": keys,
        },
    )
    assert r1.status_code == 200, r1.text
    assert len(r1.json()["artifacts"]) == 1
    assert r1.json()["content"] == "全部做对，无需额外错题巩固。"

    # 2. Code deduplication stops repeated same-skill loop
    monkeypatch.setattr(
        ws,
        "choose_skill",
        lambda **kwargs: SkillChoice(action="run_skill", skill="edu.worksheet_grading"),
    )
    r2 = client.post(
        "/v1/agent/turns",
        headers=headers,
        json={
            "thread_id": thread,
            "command_id": "dedup",
            "content": "批改作业",
            "mode": "guardian_explain",
            "attachment_keys": keys,
        },
    )
    assert r2.status_code == 200, r2.text
    assert len(r2.json()["artifacts"]) == 1

    # 3. Partial delivery when step 2 fails after step 1 succeeded
    def choose_partial(**kwargs):
        completed = kwargs.get("completed_steps") or []
        if not completed:
            return SkillChoice(action="run_skill", skill="edu.worksheet_grading")
        return SkillChoice(action="run_skill", skill="edu.lesson_pack")

    monkeypatch.setattr(ws, "choose_skill", choose_partial)
    r3 = client.post(
        "/v1/agent/turns",
        headers=headers,
        json={
            "thread_id": thread,
            "command_id": "partial-fail",
            "content": "批改并出巩固题",
            "mode": "guardian_explain",
            "attachment_keys": keys,
        },
    )
    assert r3.status_code == 200, r3.text
    assert len(r3.json()["artifacts"]) == 1
    assert r3.json()["partial_failure"] is True
    assert "后续步骤暂不可用" in r3.json()["content"]
