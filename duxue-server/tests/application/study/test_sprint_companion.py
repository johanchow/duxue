from unittest.mock import patch
import pytest
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from app.application.commands.plan_intake import PlanIntakeResult
from app.application.process_managers.companion_coordinator import CompanionCoordinator
from app.application.workflows.planning_adapter import PlanningWorkflowAdapter
from app.infrastructure.persistence.models import Sprint, Task, StudySession
from tests.support.factories import create_ward
from tests.support.fakes import StaticIntentClassifier


class Dispatcher:
    def __init__(self, db):
        self.adapter = PlanningWorkflowAdapter(db, checkpointer=InMemorySaver())

    def invoke(self, invocation):
        return self.adapter.invoke(invocation=invocation)


def test_proposed_sprint_waits_for_issued_start_and_rejects_tampering(db):
    ward = create_ward(db)
    db.commit()
    coordinator = CompanionCoordinator(
        db, dispatcher=Dispatcher(db), classifier=StaticIntentClassifier("planning")
    )
    with patch(
        "app.application.commands.plan_intake.PlanIntakeService.respond",
        return_value=PlanIntakeResult(
            assistant_text="试一轮？",
            study_action={
                "action": "sprint_prepare",
                "topic": "数学",
                "target_minutes": 20,
            },
        ),
    ):
        result = coordinator.handle(
            ward_id=ward.id,
            content="我想试一轮二十分钟数学专注挑战",
            thread_id=None,
            expected_thread_version=0,
            route_hint=None,
        )
    assert db.query(Sprint).one().status == "ready"
    assert db.query(Task).count() == 0 and db.query(StudySession).count() == 0
    action = result.interaction["actions"][0]
    altered = {**action["payload"], "action": "resume"}
    with pytest.raises(HTTPException) as error:
        coordinator.handle(
            ward_id=ward.id,
            content="",
            thread_id=result.thread_id,
            expected_thread_version=result.thread_version,
            route_hint="planning",
            structured_command={
                "command": "sprint_command",
                "interaction_id": action["id"],
                "payload": altered,
            },
        )
    assert error.value.status_code == 409
    db.rollback()
    started = coordinator.handle(
        ward_id=ward.id,
        content="",
        thread_id=result.thread_id,
        expected_thread_version=result.thread_version,
        route_hint="planning",
        structured_command={
            "command": "sprint_command",
            "interaction_id": action["id"],
            "payload": action["payload"],
        },
    )
    assert started.interaction["sprint"]["status"] == "active"
    assert db.query(Sprint).count() == 1 and db.query(Task).count() == 0


def test_unknown_task_time_is_reported_unknown_without_fabricating_session(db):
    from app.application.commands.task_execution import TaskExecutionService
    from tests.support.factories import create_task

    ward = create_ward(db)
    task = create_task(db, ward=ward, planned_minutes=None)
    result = TaskExecutionService(db).execute(ward.id, task.id, "time")
    assert result["active_seconds"] is None
    TaskExecutionService(db).execute(ward.id, task.id, "complete")
    assert task.status == "completed"
    assert db.query(StudySession).count() == 0


def test_general_conversation_can_prepare_duration_only_sprint_without_topic_gate(db):
    ward = create_ward(db)
    db.commit()
    coordinator = CompanionCoordinator(db, dispatcher=Dispatcher(db), classifier=StaticIntentClassifier('planning'))
    with patch('app.application.commands.plan_intake.PlanIntakeService.respond', return_value=PlanIntakeResult(
        assistant_text='试二十分钟。', study_action={'action':'sprint_prepare','target_minutes':20}
    )):
        result = coordinator.handle(ward_id=ward.id, content='试一轮二十分钟专注挑战', thread_id=None,
                                    expected_thread_version=0, route_hint=None)
    assert result.interaction['sprint']['topic'] == '专注挑战'
    assert db.query(Sprint).one().status == 'ready'
    assert db.query(Task).count() == db.query(StudySession).count() == 0


def test_natural_sprint_interlude_resumes_original_tutoring_run(db):
    from app.application.ports.companion import WorkflowOutcome

    class MixedDispatcher(Dispatcher):
        def invoke(self, invocation):
            if invocation.agent_type == 'tutoring':
                return WorkflowOutcome(run_status='waiting_for_ward', outcome_type='waiting',
                                       response={'kind': 'text', 'content': '先看看已知条件。', 'actions': []})
            return super().invoke(invocation)

    class AllowSwitch:
        def confirm(self, **kwargs):
            return True

    ward = create_ward(db)
    db.commit()
    coordinator = CompanionCoordinator(db, dispatcher=MixedDispatcher(db),
        classifier=StaticIntentClassifier('tutoring'), switch_verifier=AllowSwitch())
    question = coordinator.handle(ward_id=ward.id, content='这道题怎么做', thread_id=None,
                                  expected_thread_version=0, route_hint=None)
    coordinator.classifier = StaticIntentClassifier('planning')
    with patch('app.application.commands.plan_intake.PlanIntakeService.respond', return_value=PlanIntakeResult(
        assistant_text='试十分钟', study_action={'action':'sprint_prepare', 'target_minutes':10}
    )):
        proposal = coordinator.handle(ward_id=ward.id, content='我想开十分钟专注挑战自己试试',
            thread_id=question.thread_id, expected_thread_version=question.thread_version, route_hint=None)
    action = proposal.interaction['actions'][0]
    started = coordinator.handle(ward_id=ward.id, content='', thread_id=proposal.thread_id,
        expected_thread_version=proposal.thread_version, route_hint='planning',
        structured_command={'command':'sprint_command','interaction_id':action['id'],'payload':action['payload']})
    coordinator.classifier = StaticIntentClassifier('tutoring')
    resumed = coordinator.handle(ward_id=ward.id, content='刚才这道题接着讲', thread_id=question.thread_id,
                                 expected_thread_version=started.thread_version, route_hint=None)
    assert resumed.run_id == question.run_id
    assert resumed.thread_id == question.thread_id
