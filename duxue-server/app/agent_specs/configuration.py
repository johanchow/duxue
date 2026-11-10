"""Code-owned contracts and explicit, immutable Admin-exported snapshots."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2] / 'agent_specs'


@lru_cache(maxsize=1)
def code_contract():
    contract = json.loads((CODE_ROOT / 'contracts.json').read_text(encoding='utf-8'))
    for path in sorted((CODE_ROOT / 'schemas').glob('*.json')):
        contract['files'][str(path.relative_to(CODE_ROOT))] = json.loads(path.read_text(encoding='utf-8'))
    return contract


def snapshot_path() -> Path:
    return Path(os.getenv('AGENT_CONFIG_SNAPSHOT', str(CODE_ROOT.parent / 'var/admin/release.json')))


def read_snapshot(path: Path | None = None) -> dict:
    from app.agent_specs.admin_bundle import compile_bundle
    path = path or snapshot_path()
    if not path.is_file():
        raise ValueError(f'Agent配置快照不存在：{path}；请从Admin导出发布快照，不能回退仓库默认值')
    record = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(record, dict) or not {'id', 'digest', 'bundle'}.issubset(record):
        raise ValueError('需要Admin导出的完整发布快照（id/digest/bundle）')
    compiled = compile_bundle(record['bundle'])
    if record['digest'] != compiled.digest:
        raise ValueError('Admin快照摘要不匹配')
    return record


def snapshot_bundle() -> dict:
    return read_snapshot()['bundle']


_offline_catalog = None


def select_offline_snapshot(record):
    """Freeze one source for every thread in a standalone evaluation process."""
    global _offline_catalog
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.definitions import base_definitions
    snapshot = compile_bundle(record["bundle"])
    if snapshot.digest != record["digest"]:
        raise ValueError("Admin快照摘要不匹配")
    _offline_catalog = snapshot.catalog
    base_definitions.cache_clear()
    return snapshot
