"""Run standard dialogue-eval.v2 files with local scores, without cloud Datasets.

python -m scripts.run_local_dialogues --data PATH --config-snapshot EXPORT --out NEW_DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def load_records(root):
    from evals.dialogue import EpisodeRecord, TurnRecord
    records = []
    for path in sorted(root.rglob('*.json')):
        raw = json.loads(path.read_text())
        cls = {'single_turn': TurnRecord, 'episode': EpisodeRecord}.get(raw.get('type'))
        if cls is None:
            raise ValueError(f'unsupported local dialogue record: {path}')
        record = cls.model_validate(raw)
        if record.id != path.stem or record.id in {r.id for _, r in records}:
            raise ValueError('filename/id mismatch or duplicate id')
        if any(c.grading.native_evaluators for c in record.checks):
            raise ValueError('local run cannot use cloud-only evaluators')
        records.append((path, record))
    if not records:
        raise ValueError('no dialogue records')
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--config-snapshot', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    records = load_records(args.data)
    args.out.mkdir(parents=True, exist_ok=False)
    os.environ.update(OTEL_SDK_DISABLED='true', LANGFUSE_ENABLED='false',
                      AGENT_CONFIG_SOURCE='snapshot', AGENT_CONFIG_SNAPSHOT=str(args.config_snapshot.resolve()),
                      AGENT_DEBUG_AUDIT_ENABLED='true', AGENT_DEBUG_AUDIT_PATH=str((args.out/'audit.jsonl').resolve()))
    from app.agent_specs.configuration import read_snapshot, select_offline_snapshot
    from app.agent_specs.definitions import use_definitions
    from evals.configuration import _record
    from evals.local.execution import execute
    snapshot = read_snapshot()
    compiled = select_offline_snapshot(snapshot)
    _record.set(snapshot)
    def write(name, value):
        (args.out/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    write('config-snapshot.json', snapshot)
    write('inputs.json', [r.model_dump(mode='json') for _, r in records])
    write('provenance.json', {
        'mode': 'local_dialogues_local_scores', 'samples_per_task': 1, 'langfuse_used': False,
        'config_digest': snapshot['digest'],
        'input_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p, _ in records},
        'code_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                        for base in ('app', 'evals', 'math_executor', 'scripts') for p in sorted(Path(base).rglob('*.py'))},
    })
    with use_definitions(compiled.catalog):
        from app.infrastructure.ai.components import COMPONENTS
        from evals.live import build_backends, preflight
        preflight()
        spec = COMPONENTS.get('tutoring.turn')
        backend = build_backends(spec)
        if backend.semantic_grader.spec.model in {spec.model, COMPONENTS.get('tutoring.turn-backup').model}:
            raise ValueError('independent quality grader must differ from tutor and backup')
        rows = []
        for _, record in records:
            row = execute({'execution_target': 'tutoring', 'subject': 'math', 'level': 'other_k12',
                           'dataset': 'guidance-logic', 'split': 'development', 'family_id': record.id},
                          record, backend, args.data/'assets', spec)
            rows.append(row)
            write(record.id+'.result.json', row)
            print(record.id, json.dumps(row.get('status'), ensure_ascii=False), flush=True)
        write('results.json', rows)
    return 0 if all(row.get('status') == 'pass' for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
