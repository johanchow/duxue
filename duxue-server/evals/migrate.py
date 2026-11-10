"""Explicit, idempotent migration of pre-dialogue eval files (no model calls).

Run: python -m evals.migrate evals/data --write
Without --write, validate and report changes only. Old formats are not accepted
by normal loaders; this is the only compatibility boundary.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from evals.dialogue import VERSION, EpisodeRecord, JudgeRecord, TurnRecord
from evals.schema import Utterance


def message(row: dict, index: int) -> dict:
    original = Utterance.model_validate(row)
    return {'id': f'm{index + 1}', 'role': 'user' if original.author == 'ward' else 'assistant',
            'content': original.text, 'images': original.images,
            'image_target_refs': original.image_target_refs}


def source(kind: str, *, candidate: bool = False) -> dict:
    return {'kind': kind, 'coverage': 'candidate_only' if candidate else ('authored' if kind == 'synthetic' else 'observed_window'),
            'note': '迁移保留原始来源标签；格式统一不补造原话或缺失的状态证据。'}


def snapshot(context: dict, kind: str) -> dict:
    return {'origin': 'synthetic' if kind == 'synthetic' else 'reconstructed', 'context': context,
            'note': '保留旧用例注入状态；并非重新从生产数据库取得的完整快照。'}


def migrate_record(original: dict) -> dict:
    row = copy.deepcopy(original)
    if row.get('schema_version') == VERSION:
        validate_record(row)
        return row
    if row.get('type') == 'conversation_replay':
        if row.get('schema_version') not in {'conversation-eval.v1', 'conversation-eval.v2'}:
            raise ValueError('unsupported conversation version')
        row['schema_version'] = VERSION
        for check in row['checks']:
            if check['component'] == 'tutoring.turn':
                check['input_snapshot']['provenance'] = {
                    'origin': 'reconstructed',
                    'references': [check['source_observation_id']],
                    'note': '保留原回放的人工整理快照；来源引用不代表所有状态均有原始记录。',
                }
    elif 'turns' in row:
        kind = row.pop('source', 'synthetic')
        history = row.pop('initial_history', [])
        turns = row.pop('turns')
        messages = [message(m, i) for i, m in enumerate(history)]
        checks = []
        for i, turn in enumerate(turns):
            current = message({'author': 'ward', 'text': turn.pop('student_said'), 'images': turn.pop('images', [])}, len(messages))
            messages.append(current)
            checks.append({'id': f'check-{i + 1}', 'after_message': current['id'], 'component': 'tutoring.turn',
                           'input_snapshot': snapshot(turn.pop('context'), kind), **turn})
        row.update(schema_version=VERSION, type='episode', replay_mode='generated_history',
                   source=source(kind), messages=messages, checks=checks)
    elif row.get('component') == 'tutoring.leak-judge' or 'expected_leaks' in row:
        kind = row.pop('source', 'synthetic')
        problem = row.pop('problem', None)
        image = row.pop('image', None)
        expect = {'leaks': row.pop('expected_leaks'), 'criteria': [row.pop('rationale')]}
        for old, new in [('expected_reason', 'reason'), ('expected_answer_protected', 'answer_protected')]:
            if old in row:
                expect[new] = row.pop(old)
        candidate = {'id': 'candidate-1', 'role': 'assistant', 'content': row.pop('reply')}
        check = {'id': 'check-1', 'component': row.pop('component', 'tutoring.leak-judge'),
                 'candidate_id': candidate['id'], 'expect': expect,
                 'input_snapshot': {'origin': 'synthetic' if kind == 'synthetic' else 'reconstructed',
                                    'task_title': row.pop('task_title', '今日作业'), 'problem': problem,
                                    'current_request': None if problem is not None else '这题怎么做',
                                    'images': [image] if image else []}}
        row.update(schema_version=VERSION, type='judge', replay_mode='fixed_candidate', source=source(kind, candidate=True),
                   messages=[], candidates=[candidate], checks=[check])
    elif 'student_said' in row:
        kind = row.pop('source')
        messages = [message(m, i) for i, m in enumerate(row.pop('history', []))]
        current = message({'author': 'ward', 'text': row.pop('student_said'), 'images': row.pop('images', [])}, len(messages))
        messages.append(current)
        check = {'id': 'check-1', 'after_message': current['id'], 'component': row.pop('component'),
                 'input_snapshot': snapshot(row.pop('context', {}), kind), 'expect': row.pop('expect', {})}
        row.update(schema_version=VERSION, type='single_turn', replay_mode='fixed_history',
                   source=source(kind), messages=messages, checks=[check])
    else:
        raise ValueError('unknown legacy evaluation format')
    validate_record(row)
    return row


def validate_record(row: dict):
    # Local import avoids a dependency from the shared contract back to loaders.
    from evals.conversations import ConversationEval
    model = {'single_turn': TurnRecord, 'episode': EpisodeRecord,
             'judge': JudgeRecord, 'conversation_replay': ConversationEval}.get(row.get('type'))
    if model is None:
        raise ValueError('unknown evaluation type')
    return model.model_validate(row)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    files = [args.path] if args.path.is_file() else sorted(args.path.rglob('*.json'))
    if not files:
        parser.error('no JSON files found')
    # Validate the whole batch before writing any files.
    changes = []
    for file in files:
        original = json.loads(file.read_text(encoding='utf-8'))
        migrated = migrate_record(original)
        if migrated != original:
            changes.append((file, migrated))
    if args.write:
        for file, migrated in changes:
            file.write_text(json.dumps(migrated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(files)} validated; {len(changes)} {"migrated" if args.write else "would migrate"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
