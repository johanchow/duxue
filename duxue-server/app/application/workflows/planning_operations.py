"""Application use cases for multi-turn Planning operations.

Persists accepted proposals and slot bindings in PlanDraft, not in model history.
The caller owns the transaction; domain policies remain deterministic.
"""
from copy import deepcopy
from uuid import uuid4

from fastapi import HTTPException

from app.contexts.planning.domain.scheduling import (
    TaskReferenceResolver,
    can_schedule,
    local_plan_date,
)
from app.infrastructure.persistence.models import DailySchedule, PlanDraft, StudySession, Task


class PlanningOperations:
    def apply_operations(self, ward_id, plan_date, operations, *, answers=None, command_id):
        self._lock_ward(ward_id)
        if plan_date == local_plan_date():
            self.release_unfinished_tasks(ward_id, plan_date)
        for previous in self.db.query(PlanDraft).filter_by(ward_id=ward_id, plan_date=plan_date).all():
            if command_id in (previous.working_state or {}).get('processed_commands', []):
                return previous
        draft = self._ensure_draft(ward_id, plan_date)
        state = deepcopy(draft.working_state or {})
        if command_id in state.get('processed_commands', []):
            return draft
        schedule = self._schedule(ward_id, plan_date)
        self._check_not_started(schedule)
        # A new edit is a new review, never a silent confirmation retry.
        if (schedule.version if schedule else 0) != draft.base_schedule_version:
            draft.base_schedule_version = schedule.version if schedule else 0
            saved = {i['assignment_id']: deepcopy(i) for i in (schedule.items or [])} if schedule else {}
            saved.update({i['assignment_id']: deepcopy(i) for i in draft.items})
            draft.items = list(saved.values())
        tasks = {t.id: t for t in self.db.query(Task).filter_by(ward_id=ward_id).all()}
        editable = [t for t in tasks.values() if can_schedule(t.status)
                    and (t.schedule_id is None or (schedule and t.schedule_id == schedule.id))]
        candidates = [{'id': t.id, 'title': t.title} for t in editable]
        items = {i['assignment_id']: deepcopy(i) for i in draft.items}
        for ident, item in items.items():
            task = tasks.get(ident)
            if task and ident not in state.get('proposed_task_changes', {}):
                item.update(title=task.title, planned_minutes=task.planned_minutes)
        pending_ops = state.setdefault('operations', {})
        batch = state.get('active_clarification_batch') or {}
        slots = deepcopy(batch.get('slots', []))
        answers = answers or []
        if answers and batch.get('issued_draft_version') != draft.version:
            raise HTTPException(409, '澄清问题已过期，请刷新')
        invalid_slot_ids = set()
        answer_results = []
        valid_slots = []
        for slot in slots:
            if (slot.get('field') == 'target_task_ids'
                    and not slot.get('candidate_task_ids') and not slot.get('candidates')):
                invalid_slot_ids.add(slot.get('slot_id'))
                op_id = slot.get('operation_id')
                if op_id in pending_ops:
                    pending_ops[op_id].update(status='rejected', reason='未找到可修改的任务')
                    answer_results.append({'operation_id': op_id, 'status': 'rejected',
                                           'reason': pending_ops[op_id]['reason']})
                continue
            valid_slots.append(slot)
        slots = valid_slots
        remaining_slots = []
        supplied = {a.get('slot_id'): a for a in answers if a.get('slot_id') not in invalid_slot_ids}
        if set(supplied) - {s['slot_id'] for s in slots}:
            raise HTTPException(409, '澄清目标不存在或已失效')
        # Legacy duration batches are handled by the same authority-checked path.
        for slot in slots:
            op_id = slot.get('operation_id')
            if not op_id:
                target = slot['target']
                op_id = target.get('candidate_id') or 'task:' + target['task_id']
                pending_ops.setdefault(op_id, {
                    'kind': 'create' if target['kind'] == 'new_task_candidate' else 'update',
                    'title': target.get('title') or slot.get('title'),
                    'task_ids': [target['task_id']] if target.get('task_id') else [],
                    'status': 'waiting',
                })
                slot['operation_id'] = op_id
            op = pending_ops[op_id]
            answer = supplied.get(slot['slot_id'])
            if answer is None:
                remaining_slots.append(slot)
                continue
            if answer.get('skip'):
                if any(tasks[i].source == 'guardian' for i in op.get('task_ids', []) if i in tasks) and not answer.get('reason'):
                    raise HTTPException(400, '必做任务暂不安排需要说明原因')
                op.update(status='deferred', reason=answer.get('reason', '本次暂不安排'))
                for ident in op.get('task_ids', []):
                    if ident in items:
                        items[ident].update(deferred=True, unscheduled_reason=op['reason'])
                        items[ident].pop('start_at', None)
                        items[ident].pop('end_at', None)
                continue
            value = answer.get('value')
            field = slot['field']
            if field == 'target_task_ids':
                values = value if isinstance(value, list) else [value]
                allowed = set(slot.get('candidate_task_ids', []))
                if not values or not set(values) <= allowed:
                    raise HTTPException(400, '请选择当前问题中的任务')
                op['task_ids'] = list(dict.fromkeys(values))
            elif field == 'planned_minutes':
                minutes = value if isinstance(value, int) and not isinstance(value, bool) else self._duration_minutes(value)
                if minutes is None or not 1 <= minutes <= 480:
                    raise HTTPException(400, '预计时长必须为 1 到 480 分钟')
                op[field] = minutes
            elif field == 'title':
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > 300:
                    raise HTTPException(400, '请补充有效任务名字')
                op[field] = value.strip()
            elif field == 'title_conflict':
                if not isinstance(value, dict):
                    raise HTTPException(400, '标题冲突需要明确选择')
                action = value.get('action')
                allowed = {choice['value'] for choice in slot.get('choices', [])}
                if action not in allowed:
                    raise HTTPException(400, '标题冲突选项已失效')
                if action == 'use_existing':
                    task_id = value.get('task_id')
                    if task_id not in set(slot.get('candidate_task_ids', [])):
                        raise HTTPException(400, '请选择当前标题对应的任务')
                    op['kind'] = 'update'
                    op['task_ids'] = [task_id]
                elif action == 'cancel':
                    op.update(status='rejected', reason='已取消标题冲突操作')
                    answer_results.append({'operation_id': op_id, 'status': 'rejected', 'reason': op['reason']})
                op['title_conflict_resolution'] = action
            elif field == 'start_at':
                from app.contexts.planning.domain.scheduling import SchedulingService
                try:
                    SchedulingService.instant(value)
                except (ValueError, TypeError):
                    raise HTTPException(400, '开始时间格式无效') from None
                op[field] = value
            else:
                raise HTTPException(400, '不支持的澄清字段')
        slots = [s for s in remaining_slots if pending_ops[s['operation_id']].get('status') != 'deferred']
        for index, raw in enumerate(operations):
            # IDs can only come from issued slot answers, never raw model output.
            op = {k: deepcopy(v) for k, v in raw.items() if k in {
                'kind', 'references', 'title', 'planned_minutes', 'start_at',
                'after_task_reference', 'before_task_reference', 'reason'}}
            if op.get('kind') not in {'create', 'update', 'schedule', 'defer', 'delete'}:
                raise HTTPException(400, '未知计划操作')
            op_id = f'{command_id}:{index}'
            pending_ops.setdefault(op_id, {**op, 'status': 'waiting'})
        results = answer_results

        def ask(op_id, op, field, choices=None, *, choice_options=None, question=None):
            if any(s.get('operation_id') == op_id and s['field'] == field for s in slots):
                return
            slots.append({'slot_id': str(uuid4()), 'operation_id': op_id, 'field': field,
                          'title': op.get('title') or '、'.join(op.get('references') or []) or '未命名任务',
                          'target': {'kind': 'operation', 'operation_id': op_id},
                          'candidate_task_ids': choices or [],
                          'candidates': [c for c in candidates if c['id'] in (choices or [])],
                          'choices': choice_options or [], 'question': question,
                          'response_mode': 'multiple_choice' if field == 'target_task_ids' else 'structured_form'})

        def ask_title_conflict(op_id, op, conflicts):
            if any(s.get('operation_id') == op_id and s['field'] == 'title_conflict' for s in slots):
                return
            choices = [{'value': 'use_existing', 'label': '使用已有任务', 'requires_task_id': True},
                       {'value': 'create_new' if op['kind'] == 'create' else 'accept_duplicate',
                        'label': '仍然使用这个标题'},
                       {'value': 'cancel', 'label': '取消本次操作'}]
            slots.append({'slot_id': str(uuid4()), 'operation_id': op_id,
                          'field': 'title_conflict', 'title': op.get('title') or '任务标题',
                          'target': {'kind': 'operation', 'operation_id': op_id},
                          'candidate_task_ids': [candidate['id'] for candidate in conflicts],
                          'candidates': conflicts, 'choices': choices,
                          'question': '发现同名任务，请选择使用已有任务、仍然使用这个标题，或取消本次操作。',
                          'response_mode': 'single_choice'})

        for op_id, op in pending_ops.items():
            if op.get('status') in {'applied', 'deferred', 'rejected'}:
                continue
            if any(s['operation_id'] == op_id for s in slots):
                continue
            kind = op['kind']
            ids = op.get('task_ids', [])
            if kind == 'defer' and not ids:
                refs = op.get('references') or []
                deferred_candidates = [key for key, candidate in pending_ops.items()
                    if key != op_id and candidate.get('kind') == 'create' and candidate.get('status') == 'waiting'
                    and not candidate.get('task_ids') and any(
                        TaskReferenceResolver.normalise(ref) == TaskReferenceResolver.normalise(candidate.get('title'))
                        for ref in refs)]
                if deferred_candidates and len(deferred_candidates) == len(refs):
                    for key in deferred_candidates:
                        pending_ops[key]['status'] = 'deferred'
                        slots = [slot for slot in slots if slot['operation_id'] != key]
                    op['status'] = 'applied'
                    results.append({'operation_id': op_id, 'status': 'applied', 'reason': '候选本次暂不安排'})
                    continue
            if kind != 'create' and not ids:
                refs = op.get('references') or []
                matches = [TaskReferenceResolver.resolve(ref, candidates) for ref in refs]
                if not refs:
                    choices = [c['id'] for c in candidates]
                    if not choices:
                        op.update(status='rejected', reason='未找到可修改的任务')
                        results.append({'operation_id': op_id, 'status': 'rejected',
                                        'reason': op['reason']})
                        continue
                    ask(op_id, op, 'target_task_ids', choices)
                    continue
                if any(len(m) == 0 for m in matches):
                    op.update(status='rejected', reason='未找到可修改的任务')
                    results.append({'operation_id': op_id, 'status': 'rejected',
                                    'reason': op['reason']})
                    continue
                if any(len(m) != 1 for m in matches):
                    choices = [c['id'] for match in matches for c in match] or [c['id'] for c in candidates]
                    choices = list(dict.fromkeys(choices))
                    if not choices:
                        op.update(status='rejected', reason='未找到可修改的任务')
                        results.append({'operation_id': op_id, 'status': 'rejected',
                                        'reason': op['reason']})
                        continue
                    ask(op_id, op, 'target_task_ids', choices)
                    continue
                ids = list(dict.fromkeys(m[0]['id'] for m in matches))
                op['task_ids'] = ids
            targets = [tasks.get(i) for i in ids]
            if kind != 'create' and (not targets or any(t not in editable for t in targets)):
                op['status'] = 'rejected'
                results.append({'operation_id': op_id, 'status': 'rejected', 'reason': '目标已不可修改'})
                continue
            if kind == 'create':
                if not str(op.get('title') or '').strip():
                    ask(op_id, op, 'title')
                if op.get('planned_minutes') is None:
                    ask(op_id, op, 'planned_minutes')
                if any(s['operation_id'] == op_id for s in slots):
                    continue
            minutes = op.get('planned_minutes')
            if minutes is not None and (isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 480):
                ask(op_id, op, 'planned_minutes')
                continue
            if 'title' in op and op['title'] is not None and (not op['title'].strip() or len(op['title']) > 300):
                ask(op_id, op, 'title')
                continue
            if op.get('title') and op.get('title_conflict_resolution') is None:
                conflicts = TaskReferenceResolver.title_conflicts(
                    op['title'], candidates, exclude_ids=op.get('task_ids', []))
                if conflicts:
                    ask_title_conflict(op_id, op, conflicts)
                    continue
            if op.get('status') == 'rejected':
                continue
            if kind == 'defer':
                if any(t.source == 'guardian' for t in targets) and not op.get('reason'):
                    op['status'] = 'rejected'
                    results.append({'operation_id': op_id, 'status': 'rejected', 'reason': '必做任务需暂不安排原因'})
                    continue
                for task in targets:
                    item = items.setdefault(task.id, self._task_item(task))
                    item.update(deferred=True, unscheduled_reason=op.get('reason') or '本次暂不安排')
                    for field in ('start_at', 'end_at', 'after_assignment_id', 'before_assignment_id'):
                        item.pop(field, None)
                # Explicit target deferral closes prior pending operations for these targets.
                for prior_id, prior in pending_ops.items():
                    if prior_id != op_id and set(prior.get('task_ids', [])) & set(ids):
                        prior['status'] = 'deferred'
                        slots = [s for s in slots if s['operation_id'] != prior_id]
            elif kind == 'delete':
                if self.db.query(StudySession).filter(StudySession.task_id.in_(ids)).first():
                    op['status'] = 'rejected'
                    results.append({'operation_id': op_id, 'status': 'rejected',
                                    'reason': '已有学习记录的任务不能删除'})
                    continue
                proposed = {task.id for task in targets if task.schedule_id}
                deleted = set(ids) - proposed
                op['requires_confirmation'] = bool(proposed)
                proposed_deletions = state.setdefault('proposed_task_deletions', {})
                for task in targets:
                    items.pop(task.id, None)
                    if task.id in proposed:
                        proposed_deletions[task.id] = {
                            'title': task.title,
                            'planned_minutes': task.planned_minutes,
                            'task_version': task.version,
                        }
                        continue
                    tasks.pop(task.id, None)
                    if task in editable:
                        editable.remove(task)
                    self.db.delete(task)
                candidates = [candidate for candidate in candidates if candidate['id'] not in set(ids)]
                state['proposed_task_changes'] = {
                    ident: value for ident, value in state.get('proposed_task_changes', {}).items()
                    if ident not in set(ids)}
                slots = [slot for slot in slots
                         if not set(ids).intersection(pending_ops.get(slot.get('operation_id'), {}).get('task_ids', []))]
                if deleted:
                    for schedule_row in self.db.query(DailySchedule).filter_by(ward_id=ward_id).all():
                        schedule_items = [item for item in (schedule_row.items or [])
                                          if item.get('assignment_id') not in deleted]
                        if len(schedule_items) != len(schedule_row.items or []):
                            schedule_row.items = schedule_items
                            schedule_row.version += 1
                            if schedule and schedule_row.id == schedule.id:
                                draft.base_schedule_version = schedule_row.version
                    for draft_row in self.db.query(PlanDraft).filter_by(ward_id=ward_id).all():
                        if draft_row.id == draft.id:
                            continue
                        draft_items = [item for item in (draft_row.items or [])
                                       if item.get('assignment_id') not in deleted]
                        if len(draft_items) != len(draft_row.items or []):
                            draft_row.items = draft_items
                            draft_row.version += 1
            else:
                if kind == 'create' and not targets:
                    task = Task(ward_id=ward_id, title=op['title'].strip(), planned_minutes=minutes, source='ward')
                    self.db.add(task)
                    self.db.flush()
                    tasks[task.id] = task
                    editable.append(task)
                    candidates.append({'id': task.id, 'title': task.title})
                    targets = [task]
                    op['task_ids'] = [task.id]
                # Validate relative targets and times before mutating any member of a batch.
                timing = {}
                unresolved = False
                for source, output in [('after_task_reference', 'after_assignment_id'), ('before_task_reference', 'before_assignment_id')]:
                    if op.get(source):
                        match = TaskReferenceResolver.resolve(op[source], candidates)
                        if len(match) != 1 or match[0]['id'] in op.get('task_ids', []):
                            unresolved = True
                        else:
                            timing[output] = match[0]['id']
                if unresolved:
                    op['status'] = 'rejected'
                    results.append({'operation_id': op_id, 'status': 'rejected', 'reason': '相对时间参考任务不明确，请重新说明'})
                    continue
                if op.get('start_at'):
                    from app.contexts.planning.domain.scheduling import (
                        SchedulingService,
                    )
                    try:
                        SchedulingService.instant(op['start_at'])
                    except (ValueError, TypeError):
                        ask(op_id, op, 'start_at')
                        continue
                    timing.update(start_at=op['start_at'], slot_source='ward_explicit')
                for task in targets:
                    item = items.setdefault(task.id, self._task_item(task))
                    item['target_bound'] = True
                    if kind in {'update', 'create'}:
                        if op.get('title'):
                            item['title'] = op['title'].strip()
                        if minutes is not None:
                            item['planned_minutes'] = minutes
                        if task.schedule_id:
                            state.setdefault('proposed_task_changes', {})[task.id] = {
                                'title': item['title'], 'planned_minutes': item.get('planned_minutes')}
                        else:
                            task.title = item['title']
                            task.planned_minutes = item.get('planned_minutes')
                    if timing or kind == 'schedule':
                        item.pop('deferred', None)
                        item['schedule_requested'] = True
                        for field in ('after_assignment_id', 'before_assignment_id'):
                            item.pop(field, None)
                        if timing.get('after_assignment_id') or timing.get('before_assignment_id'):
                            item.pop('start_at', None)
                        item.update(timing)
                    if item.get('schedule_requested') and not item.get('start_at') and not timing:
                        ask(op_id, op, 'start_at')
            op['status'] = 'waiting' if any(s['operation_id'] == op_id for s in slots) else 'applied'
            result = {'operation_id': op_id, 'status': op['status'], 'task_ids': op.get('task_ids', [])}
            if op.get('requires_confirmation'):
                result['requires_confirmation'] = True
            results.append(result)
        self.db.flush()
        state['processed_commands'] = [*state.get('processed_commands', []), command_id]
        state['operation_results'] = results + [
            {'operation_id': op_id, 'status': op['status']} for op_id, op in pending_ops.items()
            if op.get('status') == 'waiting' and not any(r['operation_id'] == op_id for r in results)]
        for result in state['operation_results']:
            operation = pending_ops[result['operation_id']]
            result['kind'] = operation['kind']
            result['titles'] = [items[ident]['title'] for ident in operation.get('task_ids', []) if ident in items]
            if not result['titles']:
                result['titles'] = [operation.get('title') or '、'.join(operation.get('references') or []) or '未命名任务']
        if slots:
            state['active_clarification_batch'] = {'batch_id': batch.get('batch_id') or str(uuid4()), 'slots': slots}
        else:
            state.pop('active_clarification_batch', None)
        state['task_versions'] = {t.id: t.version for t in tasks.values() if t.id in items}
        pending = {s['field'] for s in slots}
        state['planning_agent_loop'] = self._loop_outcome(
            operations=operations,
            answers=answers,
            operation_results=state['operation_results'],
            pending_fields=pending,
            items=list(items.values()),
        )
        draft = self._persist_review(draft, self._draft_items_for_pool(ward_id, list(items.values())), pending, state)
        return draft

    @staticmethod
    def _task_item(task):
        return {'assignment_id': task.id, 'title': task.title, 'planned_minutes': task.planned_minutes,
                'new_task': False, 'details': task.details}

    @staticmethod
    def _loop_outcome(*, operations, answers, operation_results, pending_fields, items):
        terminal = {'applied', 'deferred', 'rejected'}
        statuses = [result.get('status') for result in operation_results]
        has_terminal = any(status in terminal for status in statuses)
        has_applied_change = any(status in {'applied', 'deferred'} for status in statuses)
        has_reviewed_plan_change = any(result.get('requires_confirmation') for result in operation_results)
        if pending_fields and has_terminal:
            status = 'partial_success'
        elif pending_fields:
            status = 'needs_clarification'
        elif statuses and all(status == 'rejected' for status in statuses):
            status = 'rejected'
        elif any(status == 'waiting' for status in statuses):
            status = 'needs_clarification'
        elif not operations and not answers and not statuses:
            status = 'no_op'
        elif has_reviewed_plan_change:
            status = 'draft_changed'
        elif has_applied_change and any(
            (item.get('schedule_requested') and (
                item.get('start_at') or item.get('after_assignment_id') or item.get('before_assignment_id')
            ))
            for item in items
        ):
            status = 'draft_changed'
        elif has_applied_change:
            status = 'task_pool_changed_only'
        else:
            status = 'no_op'
        return {
            'status': status,
            'pending_fields': sorted(pending_fields),
            'results': operation_results,
        }
