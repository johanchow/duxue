"""Identity of the fixed snapshot selected before starting evaluation workers."""
from contextvars import ContextVar

_record = ContextVar('evaluation_snapshot', default=None)


def snapshot_identity():
    record = _record.get()
    if record is None:
        from app.agent_specs.configuration import read_snapshot
        record = read_snapshot()
    return {key: record.get(key) for key in ('id', 'digest', 'kind', 'environment', 'sequence', 'revision')}
