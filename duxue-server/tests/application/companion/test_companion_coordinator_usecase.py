from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.application.ports.companion import (
    RouteDecision,
    WorkflowOutcome,
)
from app.application.process_managers.companion_coordinator import CompanionCoordinator
from app.infrastructure.persistence.models import (
    AgentCheckpoint,
    AgentRun,
    AgentStreamEvent,
    AgentTrace,
    CompanionMessage,
    ConversationThread,
    uid,
)
from tests.support.factories import create_task, create_ward
from tests.support.fakes import FakeWorkflowDispatcher, StaticIntentClassifier


def test_coordinator_skips_switch_verifier_for_same_scene_and_ui_hint(db):
    ward = create_ward(db)
    db.commit()

    class NeverVerifier:
        def confirm(self, **kwargs):
            raise AssertionError("switch verifier should not run")

    coordinator = CompanionCoordinator(
        db, dispatcher=FakeWorkflowDispatcher(), classifier=StaticIntentClassifier("tutoring"),
        switch_verifier=NeverVerifier(),
    )
    first = coordinator.handle(ward_id=ward.id, content="怎么列竖式？", thread_id=None,
                               expected_thread_version=0, route_hint=None)
    second = coordinator.handle(ward_id=ward.id, content="个位是八", thread_id=first.thread_id,
                                expected_thread_version=first.thread_version, route_hint=None)
    assert second.decision.mode == "continue"
    third = coordinator.handle(ward_id=ward.id, content="总结今天的学习", thread_id=first.thread_id,
                               expected_thread_version=second.thread_version, route_hint="tutoring")
    assert third.decision.target == "tutoring"


def test_coordinator_handles_turn_and_records_trace_and_stream_event(db):
    """协调器编排用例：分配 Thread/Run，调用工作流，更新版本，写入审计 Trace 与流事件。"""
    ward = create_ward(db)
    db.commit()

    dispatcher = FakeWorkflowDispatcher(
        WorkflowOutcome(
            run_status="waiting_for_ward",
            outcome_type="waiting",
            response={"content": "这是第一步指引"},
            checkpoint_ref="chk:test:1",
        )
    )
    coordinator = CompanionCoordinator(db, dispatcher=dispatcher, classifier=StaticIntentClassifier("tutoring"))

    result = coordinator.handle(
        ward_id=ward.id,
        content="帮我安排复习计划",
        thread_id=None,
        expected_thread_version=0,
        route_hint=None,
    )

    assert result.thread_id is not None
    assert result.thread_version == 2
    assert result.run_id is not None
    assert result.run_status == "waiting_for_ward"

    # 验证 AgentTrace 记录
    trace = db.query(AgentTrace).filter_by(thread_id=result.thread_id).first()
    assert trace is not None
    assert trace.route_target == "tutoring"
    assert trace.route_mode in {"start", "continue"}

    # 验证 AgentStreamEvent
    event = db.query(AgentStreamEvent).filter_by(run_id=result.run_id).first()
    assert event is not None
    assert event.payload == {"content": "这是第一步指引"}

    # 验证 Checkpoint
    checkpoint = db.query(AgentCheckpoint).filter_by(run_id=result.run_id).first()
    assert checkpoint is not None
    assert checkpoint.checkpoint_ref == "chk:test:1"

    messages = db.query(CompanionMessage).filter_by(thread_id=result.thread_id).order_by(CompanionMessage.thread_version).all()
    assert [(message.author_type, message.content) for message in messages] == [
        ("ward", "帮我安排复习计划"), ("companion", "这是第一步指引"),
    ]


def test_unclear_intent_writes_a_visible_reply_without_a_run(db):
    ward = create_ward(db)
    db.commit()
    result = CompanionCoordinator(db, classifier=StaticIntentClassifier("unclear")).handle(
        ward_id=ward.id, content="铁木真统一了蒙古的什么？", thread_id=None,
        expected_thread_version=0, route_hint=None,
    )
    assert result.run_id is None
    assert result.decision.target == "clarify"
    messages = db.query(CompanionMessage).filter_by(thread_id=result.thread_id).order_by(CompanionMessage.thread_version).all()
    assert [message.author_type for message in messages] == ["ward", "companion"]
    assert messages[1].content == "你想先聊哪个问题？可以再说具体一点。"
    assert messages[1].interaction_ref is None








def test_coordinator_exposes_a_controlled_failure_reply_when_workflow_raises(db):
    ward = create_ward(db)
    db.commit()

    class FailingDispatcher:
        def invoke(self, invocation):
            raise RuntimeError("provider unavailable")

    result = CompanionCoordinator(db, dispatcher=FailingDispatcher()).handle(
        ward_id=ward.id,
        content="帮我安排数学",
        thread_id=None,
        expected_thread_version=0,
        route_hint="tutoring",
    )

    assert result.run_status == "failed"
    assert result.interaction == {
        "protocol": "companion-interaction.v1",
        "kind": "error",
        "content": "暂时无法处理这条消息，请稍后重试。",
        "parts": [{"type": "text", "text": "暂时无法处理这条消息，请稍后重试。"}],
        "actions": [],
    }
    messages = db.query(CompanionMessage).filter_by(thread_id=result.thread_id).all()
    assert any(
        message.author_type == "companion" and message.content == "暂时无法处理这条消息，请稍后重试。"
        for message in messages
    )


def test_coordinator_preserves_workflow_conflicts_for_the_api_to_return(db):
    ward = create_ward(db)
    db.commit()

    class ConflictDispatcher:
        def invoke(self, invocation):
            raise HTTPException(409, "计划已变化，请重新审阅")

    with pytest.raises(HTTPException) as exc:
        CompanionCoordinator(db, dispatcher=ConflictDispatcher()).handle(
            ward_id=ward.id,
            content="确认这个计划",
            thread_id=None,
            expected_thread_version=0,
            route_hint="tutoring",
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "计划已变化，请重新审阅"


def test_coordinator_fences_late_outcome_and_records_discard_trace(db):
    """Fencing 防御：迟到的 Outcome（如 turn_id 已变）必须被静默丢弃，且记录审计 Trace。"""
    ward = create_ward(db)
    db.commit()

    coordinator = CompanionCoordinator(db, dispatcher=FakeWorkflowDispatcher(), classifier=StaticIntentClassifier("tutoring"))
    result = coordinator.handle(
        ward_id=ward.id,
        content="排个计划",
        thread_id=None,
        expected_thread_version=0,
        route_hint=None,
    )

    run = db.get(AgentRun, result.run_id)
    thread = db.get(ConversationThread, result.thread_id)

    # 模拟外部一个伪造/迟到的 Outcome，使用过期的 turn_id
    stale_turn_id = uid()
    fake_outcome = WorkflowOutcome(
        run_status="closed",
        outcome_type="completed",
        response={"content": "迟到的结果"},
    )

    accepted = coordinator.record_outcome(
        run_id=run.id,
        thread_id=thread.id,
        ward_id=ward.id,
        turn_id=stale_turn_id,
        attempt=run.attempt,
        outcome=fake_outcome,
        decision=RouteDecision(target="tutoring", mode="continue", confidence=1.0, route_reason="test"),
        duration_ms=10,
    )
    assert accepted is False

    # 状态不能被篡改
    run_refreshed = db.get(AgentRun, run.id)
    assert run_refreshed.status != "closed"

    # 应写入一条丢弃审计 Trace
    discard_trace = (
        db.query(AgentTrace)
        .filter(AgentTrace.run_id == run.id)
        .order_by(AgentTrace.created_at.desc())
        .first()
    )
    assert discard_trace.outcome.get("late_outcome_discarded") is True


def test_coordinator_command_id_idempotency_and_digest_conflict(db):
    """Command ID 幂等与冲突检测。"""
    ward = create_ward(db)
    db.commit()

    dispatcher = FakeWorkflowDispatcher()
    coordinator = CompanionCoordinator(db, dispatcher=dispatcher, classifier=StaticIntentClassifier("tutoring"))
    command_id = uid()

    # 第一次调用
    res1 = coordinator.handle(
        ward_id=ward.id,
        content="安排数学任务",
        thread_id=None,
        expected_thread_version=0,
        route_hint=None,
        command_id=command_id,
    )
    assert len(dispatcher.invocations) == 1
    assert db.query(CompanionMessage).filter_by(thread_id=res1.thread_id).count() == 2

    # 相同 command_id + 相同参数，重放返回相同结果，不再调用 dispatcher
    res2 = coordinator.handle(
        ward_id=ward.id,
        content="安排数学任务",
        thread_id=None,
        expected_thread_version=0,
        route_hint=None,
        command_id=command_id,
    )
    assert res1.model_dump() == res2.model_dump()
    assert len(dispatcher.invocations) == 1
    assert db.query(CompanionMessage).filter_by(thread_id=res1.thread_id).count() == 2

    # 相同 command_id 但参数不同，抛出 409
    with pytest.raises(HTTPException) as exc:
        coordinator.handle(
            ward_id=ward.id,
            content="篡改后的不同请求内容",
            thread_id=None,
            expected_thread_version=0,
            route_hint=None,
            command_id=command_id,
        )
    assert exc.value.status_code == 409
    assert "different payload" in exc.value.detail


def test_coordinator_thread_version_optimistic_locking(db):
    """乐观锁：expected_thread_version 滞后时抛出 409。"""
    ward = create_ward(db)
    db.commit()

    coordinator = CompanionCoordinator(db, dispatcher=FakeWorkflowDispatcher())
    res1 = coordinator.handle(
        ward_id=ward.id,
        content="你好",
        thread_id=None,
        expected_thread_version=0,
        route_hint="tutoring",
    )
    assert res1.thread_version == 2

    # 客户端依然带着旧版本号 1 重试新请求
    with pytest.raises(HTTPException) as exc:
        coordinator.handle(
            ward_id=ward.id,
            content="再帮我排一下",
            thread_id=res1.thread_id,
            expected_thread_version=1,  # 数据库当前是 2
            route_hint="tutoring",
        )
    assert exc.value.status_code == 409
    assert "conversation thread has changed" in exc.value.detail




def test_coordinator_persists_text_visual_in_companion_message_interaction_ref(db):
    from app.application.queries.run_transcript import load_visible_utterances

    ward = create_ward(db)
    db.commit()

    visual_payload = {
        "kind": "steps",
        "alt": "水循环三步",
        "steps": [{"label": "蒸发"}, {"label": "凝结"}, {"label": "降水"}],
    }
    dispatcher = FakeWorkflowDispatcher(
        WorkflowOutcome(
            run_status="waiting_for_ward",
            outcome_type="waiting",
            next_interaction={
                "protocol": "companion-interaction.v1",
                "kind": "text_visual",
                "content": "水先蒸发，再凝结，最后降下来。",
                "parts": [
                    {"type": "text", "text": "水先蒸发，再凝结，最后降下来。"},
                    {"type": "visual", "visual": visual_payload},
                ],
                "actions": [],
            },
        )
    )
    coordinator = CompanionCoordinator(db, dispatcher=dispatcher, classifier=StaticIntentClassifier("tutoring"))
    result = coordinator.handle(
        ward_id=ward.id,
        content="水循环是怎么回事",
        thread_id=None,
        expected_thread_version=0,
        route_hint="tutoring",
    )

    messages = (
        db.query(CompanionMessage)
        .filter_by(thread_id=result.thread_id)
        .order_by(CompanionMessage.thread_version)
        .all()
    )
    assert len(messages) == 2
    assert messages[0].author_type == "ward" and messages[0].interaction_ref is None
    assert messages[1].author_type == "companion"
    assert messages[1].interaction_ref == {
        "kind": "text_visual",
        "parts": [{"type": "visual", "visual": visual_payload}],
    }
    utterances = load_visible_utterances(
        db, ward_id=ward.id, thread_id=result.thread_id, exclude_turn_id=None,
    )
    assert utterances == [
        {"author": "ward", "text": "水循环是怎么回事"},
        {"author": "companion", "text": "水先蒸发，再凝结，最后降下来。", "shown_visual_kind": "steps"},
    ]


def test_coordinator_persists_pronunciation_lessons_in_companion_message_interaction_ref(db):
    ward = create_ward(db)
    db.commit()
    lessons = [{
        "lesson_ref": "lesson-1",
        "source_text": "apple",
        "locale": "en-US",
        "introduction": "apple（苹果）",
        "reading_guide": "a 发 /æ/。",
        "notes": [],
        "speech_ref": "lesson-1",
        "supported_rates": [0.5, 0.75, 1.0],
        "version": 1,
    }]
    dispatcher = FakeWorkflowDispatcher(
        WorkflowOutcome(
            run_status="waiting_for_ward",
            outcome_type="response",
            next_interaction={
                "protocol": "companion-interaction.v1",
                "kind": "pronunciation_lesson",
                "content": "apple 是苹果。",
                "parts": [{"type": "text", "text": "apple 是苹果。"}],
                "lessons": lessons,
                "actions": [],
            },
        )
    )
    coordinator = CompanionCoordinator(db, dispatcher=dispatcher, classifier=StaticIntentClassifier("tutoring"))
    result = coordinator.handle(
        ward_id=ward.id,
        content="apple 怎么读",
        thread_id=None,
        expected_thread_version=0,
        route_hint="tutoring",
    )

    messages = (
        db.query(CompanionMessage)
        .filter_by(thread_id=result.thread_id)
        .order_by(CompanionMessage.thread_version)
        .all()
    )
    assert messages[1].author_type == "companion"
    assert messages[1].interaction_ref == {"kind": "pronunciation_lesson", "lessons": lessons}




def test_companion_messages_supports_current_thread_lookup_cursor_pagination_and_previous_thread_link(db):
    from datetime import timedelta

    from app.api.v1.common import Principal, now
    from app.api.v1.companion import companion_messages, current_companion_messages

    ward = create_ward(db)
    db.commit()

    coordinator = CompanionCoordinator(db, dispatcher=FakeWorkflowDispatcher(), classifier=StaticIntentClassifier("tutoring"))
    first_thread_res = coordinator.handle(
        ward_id=ward.id,
        content="旧会话问题1",
        thread_id=None,
        expected_thread_version=0,
        route_hint="tutoring",
    )
    old_thread = db.get(ConversationThread, first_thread_res.thread_id)
    old_thread.created_at = now() - timedelta(hours=2)
    db.flush()

    second_thread_res = coordinator.handle(
        ward_id=ward.id,
        content="新会话问题1",
        thread_id=None,
        expected_thread_version=0,
        route_hint="tutoring",
    )
    second_thread_res = coordinator.handle(
        ward_id=ward.id,
        content="新会话问题2",
        thread_id=second_thread_res.thread_id,
        expected_thread_version=second_thread_res.thread_version,
        route_hint="tutoring",
    )

    principal = Principal(role="ward", user_id=ward.id)
    current_page = current_companion_messages(before_thread_version=None, limit=2, principal=principal, db=db)
    assert current_page["thread_id"] == second_thread_res.thread_id
    assert current_page["thread_version"] == second_thread_res.thread_version
    assert [m["content"] for m in current_page["messages"]] == ["新会话问题2", "请回答"]
    assert current_page["next_before_thread_version"] == 3
    assert current_page["previous_thread_id"] is None

    older_page = companion_messages(
        second_thread_res.thread_id,
        before_thread_version=current_page["next_before_thread_version"],
        limit=2,
        principal=principal,
        db=db,
    )
    assert [m["content"] for m in older_page["messages"]] == ["新会话问题1", "请回答"]
    assert older_page["next_before_thread_version"] is None
    assert older_page["previous_thread_id"] is None

    prev_thread_page = companion_messages(
        first_thread_res.thread_id,
        before_thread_version=None,
        limit=2,
        principal=principal,
        db=db,
    )
    assert [m["content"] for m in prev_thread_page["messages"]] == ["旧会话问题1", "请回答"]
    assert prev_thread_page["next_before_thread_version"] is None
    assert prev_thread_page["previous_thread_id"] is None


def test_companion_message_image_requires_owned_visible_attachment(db, monkeypatch):
    from app.api.v1.common import Principal
    from app.api.v1.companion import companion_message_image
    from app.infrastructure.persistence.models import CompanionMessage

    ward = create_ward(db)
    other = create_ward(db)
    db.commit()
    result = CompanionCoordinator(db, classifier=StaticIntentClassifier("unclear")).handle(
        ward_id=ward.id, content="看这张图", thread_id=None,
        expected_thread_version=0, route_hint=None,
    )
    message = db.query(CompanionMessage).filter_by(thread_id=result.thread_id, author_type="ward").first()
    key = f"ward/{ward.id}/companion/photo.png"
    message.attachment_refs = [key]
    db.commit()

    class FakeStorage:
        def exists(self, object_key):
            return object_key == key

        def read_bytes(self, object_key):
            assert object_key == key
            return b"image-bytes"

    monkeypatch.setattr("app.api.v1.companion.storage", FakeStorage())
    response = companion_message_image(message.id, 0, Principal(role="ward", user_id=ward.id), db)
    assert response.body == b"image-bytes"
    assert response.media_type == "image/png"
    for principal, index in [
        (Principal(role="ward", user_id=other.id), 0),
        (Principal(role="ward", user_id=ward.id), 1),
    ]:
        with pytest.raises(HTTPException) as error:
            companion_message_image(message.id, index, principal, db)
        assert error.value.status_code == 404
    message.attachment_refs = [f"ward/{other.id}/companion/photo.png"]
    db.commit()
    with pytest.raises(HTTPException) as error:
        companion_message_image(message.id, 0, Principal(role="ward", user_id=ward.id), db)
    assert error.value.status_code == 404
    message.attachment_refs = [f"ward/{ward.id}/companion/../../private.png"]
    db.commit()
    with pytest.raises(HTTPException) as error:
        companion_message_image(message.id, 0, Principal(role="ward", user_id=ward.id), db)
    assert error.value.status_code == 404
    message.attachment_refs = [f"ward/{ward.id}/companion/missing.png"]
    db.commit()
    with pytest.raises(HTTPException) as error:
        companion_message_image(message.id, 0, Principal(role="ward", user_id=ward.id), db)
    assert error.value.status_code == 404


@pytest.mark.parametrize("scene", ["tutoring"])
def test_voice_display_is_optional_and_never_replaces_source_for_workflow(db, scene):
    ward = create_ward(db)
    db.commit()
    dispatcher = FakeWorkflowDispatcher()
    coordinator = CompanionCoordinator(db, dispatcher=dispatcher, classifier=StaticIntentClassifier(scene))
    source = "嗯，我以为是负三，不对，是三。"
    display = "我以为是三。"
    result = coordinator.handle(ward_id=ward.id, content=source, voice_display_text=display,
                                thread_id=None, expected_thread_version=0, route_hint=scene)
    message = db.query(CompanionMessage).filter_by(thread_id=result.thread_id, author_type="ward").one()
    assert message.content == dispatcher.invocations[0].turn["content"] == source
    assert (message.interaction_ref or {}).get("voice_display_text") == (display if scene == "tutoring" else None)


def test_current_turn_policy_reclassifies_hinted_ward_followups(db, monkeypatch):
    from app.agent_specs.definitions import load_definitions
    from app.application.ports.companion import IntentProposal

    import json
    from pathlib import Path

    snapshot = Path(__file__).parents[2] / "fixtures/ward-turn-policy/companion.intent.json"
    unit = load_definitions().units["companion.intent"]
    monkeypatch.setitem(unit.output_schema, "required", json.loads(snapshot.read_text())["output_schema"]["required"])
    replies = iter(["homework", "homework", "pronunciation", None])
    calls = []

    class Classifier:
        def propose(self, **kwargs):
            calls.append(kwargs)
            return IntentProposal(intent="tutoring", teaching_policy=next(replies))

    class UnexpectedSwitch:
        def confirm(self, **kwargs):
            pytest.fail("a current-turn decision must not trigger a second classification")

    ward = create_ward(db)
    db.commit()
    dispatcher = FakeWorkflowDispatcher()
    coordinator = CompanionCoordinator(db, dispatcher=dispatcher, classifier=Classifier(),
                                       switch_verifier=UnexpectedSwitch())
    thread_id = None
    version = 0
    requests = ["第一步怎么想", "直接说选哪个", "triangle 怎么读", "没有可用判断"]
    for content in requests:
        result = coordinator.handle(ward_id=ward.id, thread_id=thread_id,
                                    expected_thread_version=version, content=content,
                                    route_hint="tutoring")
        thread_id, version = result.thread_id, result.thread_version
    assert [call["content"] for call in calls] == requests
    assert calls[1]["recent_utterances"][0]["text"] == requests[0]
    assert [i.agent_type for i in dispatcher.invocations] == ["tutoring"] * 3
    assert [i.turn["teaching_policy"] for i in dispatcher.invocations] == [
        "homework", "homework", "pronunciation",
    ]
    assert dispatcher.invocations[-1].turn["tutoring_intent"] == "pronunciation"
    assert result.decision.target == "clarify"
