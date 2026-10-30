from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.application.commands.companion_history import clear_history
from app.application.queries.run_transcript import load_visible_utterances

from app.api.deps import Principal, current_ward
from app.bootstrap.app import app
from app.application.process_managers.companion_coordinator import CompanionCoordinator
from app.infrastructure.persistence.models import (
    AgentRun, CompanionMessage, ConversationThread, uid,
)
from tests.support.factories import create_task, create_ward
from tests.support.fakes import FakeWorkflowDispatcher, StaticIntentClassifier


def start(db, ward_id, **kwargs):
    return CompanionCoordinator(
        db, dispatcher=FakeWorkflowDispatcher(), classifier=StaticIntentClassifier('tutoring'),
    ).handle(ward_id=ward_id, content='为什么天空是蓝色的？', thread_id=None,
             expected_thread_version=0, route_hint='tutoring', **kwargs)


def test_clear_hides_all_history_but_keeps_data_and_is_idempotent(db, client):
    ward, other = create_ward(db), create_ward(db)
    task = create_task(db, ward=ward)
    db.commit()
    first = start(db, ward.id)
    second = start(db, ward.id)
    foreign = start(db, other.id)
    messages_before = db.query(CompanionMessage).count()
    message = db.query(CompanionMessage).filter_by(thread_id=first.thread_id, author_type='ward').one()
    message.attachment_refs = [f'ward/{ward.id}/companion/test.png']
    db.commit()
    app.dependency_overrides[current_ward] = lambda: Principal(ward.id, 'ward')
    try:
        command = {'command_id': uid()}
        response = client.post('/companion/history/clear', json=command)
        assert response.status_code == 200, response.text
        assert response.json()['history_generation'] == 1
        assert client.get('/companion/threads/current/messages').json()['messages'] == []
        for thread_id in (first.thread_id, second.thread_id, foreign.thread_id):
            assert client.get(f'/companion/threads/{thread_id}/messages').status_code == 404
        with patch('app.api.v1.companion.storage.read_bytes') as read:
            assert client.get(f'/companion/messages/{message.id}/attachments/0').status_code == 404
            read.assert_not_called()
        assert client.get(f'/companion/runs/{first.run_id}/events').status_code == 404
        assert db.query(CompanionMessage).count() == messages_before
        assert db.get(type(task), task.id) is not None
        assert db.get(AgentRun, foreign.run_id).status != 'cancelled'
        assert db.get(ConversationThread, first.thread_id).focus_run_ref is None
        fresh = start(db, ward.id)
        assert load_visible_utterances(db, ward_id=ward.id, thread_id=fresh.thread_id, exclude_turn_id=db.get(AgentRun, fresh.run_id).current_turn_id) == []
        assert fresh.thread_id not in (first.thread_id, second.thread_id)
        assert client.post('/companion/history/clear', json=command).json() == response.json()
        visible = client.get('/companion/threads/current/messages').json()
        assert visible['thread_id'] == fresh.thread_id
        assert visible['previous_thread_id'] is None
        assert client.get(f'/companion/threads/{fresh.thread_id}/messages').json()['previous_thread_id'] is None
    finally:
        app.dependency_overrides.pop(current_ward, None)


def test_clear_rejects_stale_turn_and_completed_command_replay(db, client):
    ward = create_ward(db)
    db.commit()
    command_id = uid()
    first = start(db, ward.id, command_id=command_id)
    app.dependency_overrides[current_ward] = lambda: Principal(ward.id, 'ward')
    try:
        assert client.post('/companion/history/clear', json={'command_id': uid()}).status_code == 200
        with pytest.raises(HTTPException) as error:
            start(db, ward.id, command_id=command_id)
        assert error.value.status_code == 409
        db.rollback()
        with pytest.raises(HTTPException) as error:
            CompanionCoordinator(db).handle(ward_id=ward.id, content='继续', thread_id=first.thread_id,
                expected_thread_version=None, route_hint='tutoring')
        assert error.value.status_code == 404
    finally:
        app.dependency_overrides.pop(current_ward, None)


def test_clear_during_workflow_discards_late_reply(db, client):
    ward = create_ward(db)
    db.commit()
    app.dependency_overrides[current_ward] = lambda: Principal(ward.id, 'ward')
    class ClearingDispatcher(FakeWorkflowDispatcher):
        def invoke(self, invocation):
            # A separate request/session must invalidate the coordinator's cached ORM state.
            with Session(bind=db.get_bind()) as clearing_db:
                clear_history(clearing_db, ward_id=ward.id, command_id=uid())
            return super().invoke(invocation)
    try:
        with pytest.raises(HTTPException) as error:
            CompanionCoordinator(db, dispatcher=ClearingDispatcher(), classifier=StaticIntentClassifier('tutoring')).handle(
                ward_id=ward.id, content='问题', thread_id=None, expected_thread_version=0, route_hint='tutoring')
        assert error.value.status_code == 409
        assert db.query(CompanionMessage).filter_by(ward_id=ward.id, author_type='companion').count() == 0
        assert client.get('/companion/threads/current/messages').json()['messages'] == []
    finally:
        app.dependency_overrides.pop(current_ward, None)


def test_clear_command_validation_and_ward_isolation(db, client):
    ward, other = create_ward(db), create_ward(db)
    db.commit()
    command_id = uid()
    app.dependency_overrides[current_ward] = lambda: Principal(ward.id, 'ward')
    try:
        assert client.post('/companion/history/clear', json={'command_id': 'x' * 36}).status_code == 422
        assert client.post('/companion/history/clear', json={'command_id': command_id}).status_code == 200
        app.dependency_overrides[current_ward] = lambda: Principal(other.id, 'ward')
        assert client.post('/companion/history/clear', json={'command_id': command_id}).status_code == 409
        assert db.get(type(other), other.id).history_generation == 0
    finally:
        app.dependency_overrides.pop(current_ward, None)
