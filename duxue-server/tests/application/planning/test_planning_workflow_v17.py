from datetime import date

import pytest
from fastapi import HTTPException

from app.application.workflows.planning_domain_service import PlanningDomainService
from app.infrastructure.persistence.models import PlanDraft, Task
from tests.support.factories import create_task, create_ward

DAY = date(2026, 9, 20)


def operate(service, ward, operations=(), answers=(), command_id='turn-1'):
    return service.apply_operations(ward.id, DAY, list(operations), answers=list(answers), command_id=command_id)


def scheduled(service, ward):
    return service.save_draft(ward.id, DAY, [{'new_task': True, 'title': '数学', 'planned_minutes': 40, 'start_at': '2026-09-20T19:00:00'}])


def test_missing_name_candidate_preserves_duration_and_registers_once(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [{'kind': 'create', 'planned_minutes': 20}])
    slot = draft.working_state['active_clarification_batch']['slots'][0]
    assert slot['field'] == 'title'
    assert db.query(Task).count() == 0
    reply = [{'slot_id': slot['slot_id'], 'value': '科学阅读'}]
    draft = operate(service, ward, answers=reply, command_id='turn-2')
    operate(service, ward, answers=reply, command_id='turn-2')
    assert [(t.title, t.planned_minutes) for t in db.query(Task)] == [('科学阅读', 20)]
    assert not draft.pending_fields
    assert not service.plan_draft_view(ward.id, draft.id)['confirm_enabled']


def test_content_patch_preserves_other_slots_and_detects_overlap(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    service.save_draft(ward.id, DAY, [
        {'new_task': True, 'title': '数学', 'planned_minutes': 40, 'start_at': '2026-09-20T19:00:00'},
        {'new_task': True, 'title': '英语', 'planned_minutes': 20, 'start_at': '2026-09-20T19:40:00'},
    ])
    draft = operate(service, ward, [{'kind': 'update', 'references': ['数学'], 'title': '数学练习', 'planned_minutes': 60}])
    math = db.query(Task).filter_by(title='数学练习').one()
    assert math.planned_minutes == 60
    view = service.plan_draft_view(ward.id, draft.id)
    assert len(view['items']) == 2
    assert not view['confirm_enabled']
    assert any(i['schedule_conflict'] for i in view['items'])


def test_ambiguous_update_survives_multiselect_answer(db):
    ward = create_ward(db)
    first = create_task(db, ward=ward, title='英语听力', planned_minutes=20)
    second = create_task(db, ward=ward, title='英语阅读', planned_minutes=25)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [{'kind': 'update', 'references': ['英语'], 'planned_minutes': 30}])
    slot = draft.working_state['active_clarification_batch']['slots'][0]
    assert first.planned_minutes == 20
    draft = operate(service, ward, answers=[{'slot_id': slot['slot_id'], 'value': [first.id, second.id]}], command_id='choose')
    assert first.planned_minutes == second.planned_minutes == 30
    assert not draft.pending_fields


def test_batch_invalid_target_does_not_partially_update(db):
    ward = create_ward(db)
    first = create_task(db, ward=ward, title='听力', planned_minutes=20)
    second = create_task(db, ward=ward, title='阅读', planned_minutes=25, status='completed')
    draft = operate(PlanningDomainService(db), ward, [{'kind': 'update', 'references': ['听力', '阅读'], 'planned_minutes': 30}])
    assert first.planned_minutes == 20
    assert second.planned_minutes == 25
    assert draft.pending_fields


def test_explicit_defer_closes_candidate_slot_without_creating_task(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [{'kind': 'create', 'title': '英语'}])
    slot = draft.working_state['active_clarification_batch']['slots'][0]
    draft = operate(service, ward, answers=[{'slot_id': slot['slot_id'], 'skip': True, 'reason': '下次安排'}], command_id='defer')
    assert not draft.pending_fields
    assert db.query(Task).count() == 0


def test_confirmation_rejects_task_changed_since_review(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = scheduled(service, ward)
    task = db.query(Task).one()
    task.planned_minutes = 60
    db.flush()
    with pytest.raises(HTTPException) as exc:
        service.confirm(ward.id, draft.id, draft.version)
    assert exc.value.status_code == 409
    assert task.schedule_id is None


def test_revision_preserves_old_plan_until_confirm_and_records_history(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    original = scheduled(service, ward)
    schedule = service.confirm(ward.id, original.id, original.version)
    db.commit()
    task = db.query(Task).one()
    old_version = schedule.version
    revision = operate(service, ward, [{'kind': 'update', 'references': ['数学'], 'planned_minutes': 60}])
    assert revision.id != original.id
    assert original.status == 'confirmed'
    assert task.planned_minutes == 40
    assert schedule.version == old_version
    assert service.plan_draft_view(ward.id, revision.id)['items'][0]['planned_minutes'] == 60
    service.confirm(ward.id, revision.id, revision.version)
    assert task.planned_minutes == 60
    assert schedule.version > old_version
    assert schedule.history[-1]['version'] == old_version
    assert schedule.history[-1]['items'][0]['planned_minutes'] == 40
    assert db.query(PlanDraft).count() == 2


def test_revision_rejected_if_study_started(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = scheduled(service, ward)
    service.confirm(ward.id, draft.id)
    db.query(Task).one().status = 'in_progress'
    db.flush()
    with pytest.raises(HTTPException) as exc:
        operate(service, ward, [{'kind': 'update', 'references': ['数学'], 'planned_minutes': 60}])
    assert exc.value.status_code == 409


def test_new_draft_merges_existing_schedule_instead_of_erasing_it(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    first = scheduled(service, ward)
    schedule = service.confirm(ward.id, first.id)
    second = service.save_draft(ward.id, DAY, [{'new_task': True, 'title': '英语', 'planned_minutes': 20, 'start_at': '2026-09-20T19:20:00'}])
    assert not service.plan_draft_view(ward.id, second.id)['confirm_enabled']
    with pytest.raises(HTTPException):
        service.confirm(ward.id, second.id)
    assert len([t for t in db.query(Task) if t.schedule_id == schedule.id]) == 1


def test_legacy_http_route_does_not_attach_task_before_confirmation(db):
    from app.api.deps import Principal
    from app.api.schemas import PlanDraft as DraftInput
    from app.api.v1.planning import save_plan
    ward = create_ward(db)
    task = create_task(db, ward=ward)
    result = save_plan(ward.id, DAY, DraftInput(plan_date=DAY, items=[{
        'assignment_id': task.id, 'title': task.title, 'planned_minutes': 30}]), Principal(ward.id, 'ward'), db)
    assert task.schedule_id is None
    assert result['draft_id']


def test_content_partial_turn_keeps_independent_changes_and_can_defer_by_name(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [{'kind': 'create', 'title': '英语'},
        {'kind': 'create', 'title': '数学', 'planned_minutes': 30, 'start_at': '2026-09-20T19:00:00'}])
    assert draft.pending_fields
    draft = operate(service, ward, [{'kind': 'defer', 'references': ['英语']}], command_id='next')
    assert service.plan_draft_view(ward.id, draft.id)['confirm_enabled']
    assert db.query(Task).count() == 1


def test_schedule_missing_anchor_then_reply_does_not_duplicate_task(db):
    ward = create_ward(db)
    task = create_task(db, ward=ward, title='数学', planned_minutes=30)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [{'kind': 'schedule', 'references': ['数学']}])
    slot = draft.working_state['active_clarification_batch']['slots'][0]
    assert slot['field'] == 'start_at'
    draft = operate(service, ward, answers=[{'slot_id': slot['slot_id'], 'value': '2026-09-20T19:00:00'}], command_id='time')
    assert service.plan_draft_view(ward.id, draft.id)['confirm_enabled']
    assert draft.items[0]['assignment_id'] == task.id


def test_multiselect_cannot_select_foreign_task(db):
    ward = create_ward(db)
    create_task(db, ward=ward, title='英语听力')
    create_task(db, ward=ward, title='英语阅读')
    other = create_task(db, ward=create_ward(db))
    service = PlanningDomainService(db)
    draft = operate(service, ward, [{'kind': 'update', 'references': ['英语'], 'planned_minutes': 20}])
    slot = draft.working_state['active_clarification_batch']['slots'][0]
    with pytest.raises(HTTPException):
        operate(service, ward, answers=[{'slot_id': slot['slot_id'], 'value': [other.id]}], command_id='bad')
    assert other.planned_minutes == 30


def test_adapter_model_operations_reach_review_and_confirmation(db, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    from app.application.commands.plan_intake import PlanIntakeResult, PlanIntakeService
    from app.application.ports.companion import RunInvocation
    from app.application.workflows.planning_adapter import PlanningWorkflowAdapter
    from app.infrastructure.persistence.models import AgentRun, ConversationThread
    ward = create_ward(db)
    thread = ConversationThread(ward_id=ward.id)
    db.add(thread)
    db.flush()
    run = AgentRun(thread_id=thread.id, ward_id=ward.id, agent_type='planning', run_ref='test')
    db.add(run)
    db.flush()
    adapter = PlanningWorkflowAdapter(db, checkpointer=InMemorySaver())
    monkeypatch.setattr(PlanIntakeService, 'respond', lambda *a, **k: PlanIntakeResult(
        assistant_text='已记录', operations=[{'kind': 'create', 'planned_minutes': 20}]))
    first = adapter.invoke(invocation=RunInvocation(run_id=run.id, thread_id=thread.id,
        ward_id=ward.id, agent_type='planning', command_id='name-first', turn={'content': '加二十分钟的任务'}))
    assert '名字' in first.next_interaction['content']
    draft = db.query(PlanDraft).one()
    slot = draft.working_state['active_clarification_batch']['slots'][0]
    monkeypatch.setattr(PlanIntakeService, 'respond', lambda *a, **k: PlanIntakeResult(
        assistant_text='安排数学', slot_updates=[{'slot_id': slot['slot_id'], 'value': '数学'}],
        operations=[{'kind': 'schedule', 'references': ['数学'], 'start_at': '2026-09-20T19:00:00'}]))
    second = adapter.invoke(invocation=RunInvocation(run_id=run.id, thread_id=thread.id,
        ward_id=ward.id, agent_type='planning', command_id='name-second', turn={'content': '数学，十九点开始'}))
    assert second.next_interaction['kind'] == 'plan_confirm_list'
    result = adapter.invoke(invocation=RunInvocation(run_id=run.id, thread_id=thread.id,
        ward_id=ward.id, agent_type='planning', command_id='name-confirm', turn={'structured_command': {
            'command': 'confirm_plan', 'payload': {'draft_id': draft.id, 'expected_draft_version': draft.version}}}))
    assert result.run_status == 'closed'
    assert db.query(Task).one().schedule_id is not None


def test_content_edit_recomputes_relative_successor(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [
        {'kind': 'create', 'title': '数学', 'planned_minutes': 40, 'start_at': '2026-09-20T19:00:00'},
        {'kind': 'create', 'title': '英语', 'planned_minutes': 20, 'after_task_reference': '数学'}])
    english = next(i for i in draft.items if i['title'] == '英语')
    assert english['start_at'].endswith('19:40:00')
    draft = operate(service, ward, [{'kind': 'update', 'references': ['数学'], 'planned_minutes': 60}], command_id='longer')
    english = next(i for i in draft.items if i['title'] == '英语')
    assert english['start_at'].endswith('20:00:00')


def test_slot_invalid_duration_cannot_treat_clock_as_elapsed_minutes(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [{'kind': 'create', 'title': '数学'}])
    slot = draft.working_state['active_clarification_batch']['slots'][0]
    with pytest.raises(HTTPException):
        operate(service, ward, answers=[{'slot_id': slot['slot_id'], 'value': '十九点三十分'}], command_id='clock')
    assert db.query(Task).count() == 0


def test_versioned_task_write_cannot_overwrite_concurrent_session(db, db_engine):
    from sqlalchemy.orm import Session
    from sqlalchemy.orm.exc import StaleDataError
    ward = create_ward(db)
    task = create_task(db, ward=ward)
    db.commit()
    with Session(db_engine) as other:
        old = other.get(Task, task.id)
        task.planned_minutes = 45
        db.commit()
        old.planned_minutes = 60
        with pytest.raises(StaleDataError):
            other.commit()
        other.rollback()
    db.refresh(task)
    assert task.planned_minutes == 45


def test_refresh_after_external_task_edit_uses_new_content_not_stale_snapshot(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = scheduled(service, ward)
    task = db.query(Task).one()
    task.planned_minutes = 60
    db.flush()
    draft = operate(service, ward, command_id='refresh')
    assert draft.items[0]['planned_minutes'] == 60
    assert draft.items[0]['end_at'].endswith('20:00:00')


def test_unknown_target_update_never_creates_task(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [{'kind': 'update', 'references': ['不存在'], 'planned_minutes': 30}])
    assert db.query(Task).count() == 0
    assert draft.pending_fields == ['target_task_ids']


def test_explicit_bound_overlapping_times_remain_visible_as_conflict(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [
        {'kind': 'create', 'title': '数学', 'planned_minutes': 30, 'start_at': '2026-09-20T19:00:00'},
        {'kind': 'create', 'title': '英语', 'planned_minutes': 30, 'start_at': '2026-09-20T19:00:00'}])
    view = service.plan_draft_view(ward.id, draft.id)
    assert not view['confirm_enabled']
    assert view['conflicts'][0]['code'] == 'time_overlap'
    assert all(i['start_at'].endswith('19:00:00') for i in view['items'])


def test_adjacent_time_slots_are_not_overlapping(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [
        {'kind': 'create', 'title': '数学', 'planned_minutes': 30, 'start_at': '2026-09-20T19:00:00'},
        {'kind': 'create', 'title': '英语', 'planned_minutes': 30, 'start_at': '2026-09-20T19:30:00'},
    ])
    view = service.plan_draft_view(ward.id, draft.id)
    assert view['conflicts'] == []
    assert view['confirm_enabled']


def test_duplicate_new_title_requires_explicit_clarification(db):
    ward = create_ward(db)
    existing = create_task(db, ward=ward, title='数学', planned_minutes=20)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [{'kind': 'create', 'title': ' 数学 ', 'planned_minutes': 30}])
    assert db.query(Task).count() == 1
    slot = draft.working_state['active_clarification_batch']['slots'][0]
    assert slot['field'] == 'title_conflict'
    assert existing.id in slot['candidate_task_ids']
    draft = operate(service, ward, answers=[{
        'slot_id': slot['slot_id'], 'value': {'action': 'create_new'},
    }], command_id='duplicate-title-confirm')
    assert db.query(Task).count() == 2
    assert not draft.pending_fields


def test_duplicate_new_title_can_bind_to_existing_task_after_choice(db):
    ward = create_ward(db)
    existing = create_task(db, ward=ward, title='数学', planned_minutes=20)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [{'kind': 'create', 'title': '数学', 'planned_minutes': 30}])
    slot = draft.working_state['active_clarification_batch']['slots'][0]
    draft = operate(service, ward, answers=[{
        'slot_id': slot['slot_id'],
        'value': {'action': 'use_existing', 'task_id': existing.id},
    }], command_id='duplicate-title-existing')
    assert db.query(Task).count() == 1
    assert db.query(Task).one().planned_minutes == 30
    assert not draft.pending_fields


def test_duplicate_rename_requires_clarification_and_preserves_task_until_answer(db):
    ward = create_ward(db)
    first = create_task(db, ward=ward, title='数学', planned_minutes=20)
    second = create_task(db, ward=ward, title='英语', planned_minutes=20)
    service = PlanningDomainService(db)
    draft = operate(service, ward, [{'kind': 'update', 'references': ['数学'], 'title': ' 英语 '}])
    assert first.title == '数学'
    slot = draft.working_state['active_clarification_batch']['slots'][0]
    assert slot['field'] == 'title_conflict'
    assert second.id in slot['candidate_task_ids']
    draft = operate(service, ward, answers=[
        {'slot_id': slot['slot_id'], 'value': {'action': 'cancel'}},
    ], command_id='duplicate-rename-cancel')
    assert first.title == '数学'
    assert not draft.pending_fields


def test_legacy_structured_new_task_title_conflict_is_explicit_error(db):
    ward = create_ward(db)
    create_task(db, ward=ward, title='数学', planned_minutes=20)
    service = PlanningDomainService(db)
    with pytest.raises(HTTPException) as exc:
        service.save_draft(ward.id, DAY, [{
            'new_task': True, 'title': ' 数学 ', 'planned_minutes': 30,
        }])
    assert exc.value.status_code == 409
    assert exc.value.detail['code'] == 'duplicate_task_title'


def test_legacy_structured_rename_title_conflict_is_explicit_error(db):
    ward = create_ward(db)
    first = create_task(db, ward=ward, title='数学', planned_minutes=20)
    second = create_task(db, ward=ward, title='英语', planned_minutes=20)
    service = PlanningDomainService(db)
    with pytest.raises(HTTPException) as exc:
        service.save_draft(ward.id, DAY, [{
            'assignment_id': first.id, 'new_task': False,
            'title': second.title, 'planned_minutes': 20,
        }])
    assert exc.value.status_code == 409
    assert exc.value.detail['code'] == 'duplicate_task_title'


def test_planning_migration_backfills_confirmed_slots_and_protects_history(db, db_engine):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    migration = importlib.import_module('migrations.versions.20260920_19_planning_revisions')
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = scheduled(service, ward)
    schedule = service.confirm(ward.id, draft.id)
    db.commit()
    with db_engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()
        assert 'items' not in {c['name'] for c in inspect(connection).get_columns('daily_schedules')}
        migration.upgrade()
    db.expire_all()
    assert schedule.items[0]['title'] == '数学'
    assert schedule.items[0]['start_at'].endswith('19:00:00')
    revision = operate(service, ward, [{'kind': 'update', 'references': ['数学'], 'planned_minutes': 60}])
    service.confirm(ward.id, revision.id)
    db.commit()
    with db_engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        with pytest.raises(RuntimeError, match='revision history'):
            migration.downgrade()
        assert 'items' in {c['name'] for c in inspect(connection).get_columns('daily_schedules')}


def test_confirm_body_requires_reviewed_version_and_rejects_missing_time(db):
    from app.api.deps import Principal
    from app.api.v1.planning import ConfirmDraftRequest, confirm_plan
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = service.save_draft(ward.id, DAY, [{'new_task': True, 'title': '数学', 'planned_minutes': 30}])
    db.commit()
    with pytest.raises(HTTPException) as exc:
        confirm_plan(ward.id, DAY, None, Principal(ward.id, 'ward'), db)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException):
        confirm_plan(ward.id, DAY, ConfirmDraftRequest(draft_id=draft.id, expected_draft_version=draft.version), Principal(ward.id, 'ward'), db)
    assert db.query(Task).one().schedule_id is None
