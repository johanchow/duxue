"""A local replay cannot silently load unrelated JSON or cloud scoring rules."""
import json

import pytest

from scripts.run_local_dialogues import load_records


def test_local_dialogues_requires_nonempty_task_directory(tmp_path):
    with pytest.raises(ValueError, match='no dialogue records'):
        load_records(tmp_path)


def test_local_dialogues_rejects_unrelated_json(tmp_path):
    (tmp_path / 'snapshot.json').write_text(json.dumps({'bundle': {}}))
    with pytest.raises(ValueError, match='unsupported local dialogue record'):
        load_records(tmp_path)
