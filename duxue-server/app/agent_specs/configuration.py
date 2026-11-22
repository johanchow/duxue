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


def fetch_admin_snapshot(
    channel: str | None = None,
    *,
    source_url: str | None = None,
    token: str | None = None,
) -> dict:
    """Fetch and validate one immutable Admin configuration snapshot for a single eval run."""
    from urllib.parse import urlsplit

    import httpx
    from dotenv import load_dotenv

    from app.agent_specs.admin_bundle import compile_bundle

    if not (source_url or os.getenv("AGENT_CONFIG_SOURCE_URL")) or not (
        token or os.getenv("AGENT_ADMIN_INTERNAL_TOKEN")
    ):
        load_dotenv(CODE_ROOT.parent / ".env", override=False)

    source = (source_url or os.getenv("AGENT_CONFIG_SOURCE_URL", "")).rstrip("/")
    secret = token or os.getenv("AGENT_ADMIN_INTERNAL_TOKEN", "")
    if not source or len(secret) < 32:
        raise ValueError(
            "离线评测默认直接从 Admin 读取配置；请配置 AGENT_CONFIG_SOURCE_URL 和至少 32 字符的 AGENT_ADMIN_INTERNAL_TOKEN"
        )
    effective_channel = (
        channel or os.getenv("AGENT_CONFIG_CHANNEL") or "working-draft"
    ).strip()
    if effective_channel not in {"working-draft", "release"}:
        raise ValueError(f"未知 Admin 配置渠道：{effective_channel}")

    expected_env = (
        "prod" if os.getenv("APP_ENV") in {"production", "prod"} else "test"
    )
    headers = {"Authorization": "Bearer " + secret}

    if effective_channel == "working-draft":
        if expected_env != "test" or urlsplit(source).hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("工作草稿仅允许本机连接测试 Admin")
        response = httpx.get(source + "/working-draft", headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("environment") != "test":
            raise ValueError("草稿环境不匹配")
        draft = data.get("draft")
        if draft is not None:
            record = {
                **draft,
                "kind": "draft",
                "environment": data["environment"],
                "source_channel": "working-draft",
            }
        else:
            rel_resp = httpx.get(source + "/release", headers=headers, timeout=10)
            rel_resp.raise_for_status()
            rel_data = rel_resp.json()
            if rel_data.get("environment") != "test" or not rel_data.get("release"):
                raise ValueError("测试 Admin 没有工作草稿或发布")
            record = {
                **rel_data["release"],
                "kind": "release",
                "environment": rel_data["environment"],
                "revision": rel_data.get("generation"),
                "source_channel": "working-draft",
            }
    else:
        response = httpx.get(source + "/release", headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("environment") != expected_env or not data.get("release"):
            raise ValueError(f"Admin {expected_env} 环境没有可用发布")
        record = {
            **data["release"],
            "kind": "release",
            "environment": data["environment"],
            "revision": data.get("generation"),
            "source_channel": "release",
        }

    if not isinstance(record.get("bundle"), dict):
        raise TypeError("Admin 返回的配置缺少 bundle")
    compiled = compile_bundle(record["bundle"])
    if record.get("digest") and record["digest"] != compiled.digest:
        raise ValueError("Admin配置摘要不匹配")
    record["digest"] = compiled.digest
    return record


def load_evaluation_snapshot(
    *,
    snapshot_file: Path | str | None = None,
    channel: str | None = None,
) -> dict:
    """Load pinned config for evaluation: Admin DB by default, file only when explicitly provided."""
    if snapshot_file is not None:
        return read_snapshot(Path(snapshot_file))
    return fetch_admin_snapshot(channel=channel)


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
