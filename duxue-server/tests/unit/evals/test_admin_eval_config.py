"""Tests for fetching and freezing Admin configurations in offline evaluations."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.agent_specs.configuration import (
    fetch_admin_snapshot,
    load_evaluation_snapshot,
    read_snapshot,
)


def _sample_record() -> dict:
    return read_snapshot()


def test_fetch_admin_snapshot_working_draft(monkeypatch):
    sample = _sample_record()
    calls: list[str] = []

    def fake_get(url, *, headers=None, timeout=None):
        calls.append(url)
        assert headers == {"Authorization": "Bearer " + "x" * 32}
        return httpx.Response(
            200,
            json={
                "environment": "test",
                "draft": {
                    "id": "draft-123",
                    "revision": 19,
                    "digest": sample["digest"],
                    "bundle": sample["bundle"],
                },
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setenv("APP_ENV", "development")

    record = fetch_admin_snapshot(
        "working-draft",
        source_url="http://127.0.0.1:3021/api/internal",
        token="x" * 32,
    )
    assert calls == ["http://127.0.0.1:3021/api/internal/working-draft"]
    assert record["id"] == "draft-123"
    assert record["kind"] == "draft"
    assert record["revision"] == 19
    assert record["environment"] == "test"
    assert record["source_channel"] == "working-draft"
    assert record["digest"] == sample["digest"]


def test_fetch_admin_snapshot_working_draft_falls_back_to_release(monkeypatch):
    sample = _sample_record()
    calls: list[str] = []

    def fake_get(url, *, headers=None, timeout=None):
        calls.append(url)
        if url.endswith("/working-draft"):
            return httpx.Response(
                200,
                json={"environment": "test", "draft": None},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(
            200,
            json={
                "environment": "test",
                "generation": 13,
                "release": {
                    "id": "rel-13",
                    "digest": sample["digest"],
                    "bundle": sample["bundle"],
                },
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setenv("APP_ENV", "development")

    record = fetch_admin_snapshot(
        "working-draft",
        source_url="http://localhost:3021/api/internal",
        token="y" * 32,
    )
    assert calls == [
        "http://localhost:3021/api/internal/working-draft",
        "http://localhost:3021/api/internal/release",
    ]
    assert record["id"] == "rel-13"
    assert record["kind"] == "release"
    assert record["revision"] == 13
    assert record["source_channel"] == "working-draft"


def test_fetch_admin_snapshot_rejects_remote_working_draft(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    with pytest.raises(ValueError, match="工作草稿仅允许本机连接测试 Admin"):
        fetch_admin_snapshot(
            "working-draft",
            source_url="https://admin.example.com/api/internal",
            token="x" * 32,
        )


def test_fetch_admin_snapshot_release_rejects_digest_mismatch(monkeypatch):
    sample = _sample_record()

    def fake_get(url, *, headers=None, timeout=None):
        return httpx.Response(
            200,
            json={
                "environment": "test",
                "generation": 13,
                "release": {
                    "id": "rel-13",
                    "digest": "0" * 64,
                    "bundle": sample["bundle"],
                },
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setenv("APP_ENV", "development")

    with pytest.raises(ValueError, match="摘要不匹配"):
        fetch_admin_snapshot(
            "release",
            source_url="http://127.0.0.1:3021/api/internal",
            token="z" * 32,
        )


def test_load_evaluation_snapshot_defaults_to_admin(monkeypatch):
    called: list[str | None] = []
    sample = {**_sample_record(), "source_channel": "working-draft"}

    def fake_fetch(channel=None, **_kwargs):
        called.append(channel)
        return sample

    monkeypatch.setattr("app.agent_specs.configuration.fetch_admin_snapshot", fake_fetch)

    result = load_evaluation_snapshot(channel="release")
    assert called == ["release"]
    assert result is sample


def test_local_eval_cli_defaults_to_admin_without_snapshot_arg(monkeypatch, tmp_path: Path):
    from types import SimpleNamespace

    import evals.live
    from evals.local.__main__ import main as local_main

    base = read_snapshot(Path("tests/fixtures/admin-release.json"))
    sample = {
        **base,
        "id": "draft-19",
        "kind": "draft",
        "revision": 19,
        "environment": "test",
        "source_channel": "working-draft",
    }
    fetched_channels: list[str | None] = []

    def fake_fetch(channel=None, **_kwargs):
        fetched_channels.append(channel)
        return sample

    monkeypatch.setattr("app.agent_specs.configuration.fetch_admin_snapshot", fake_fetch)
    monkeypatch.setattr(
        evals.live,
        "build_backends",
        lambda _spec: SimpleNamespace(
            semantic_grader=SimpleNamespace(
                spec=SimpleNamespace(model="distinct-judge", accepts_images=True),
                metadata=lambda: {"model": "distinct-judge"},
            )
        ),
    )
    out = tmp_path / "admin-preflight"
    rc = local_main(
        [
            "run",
            "--data",
            "evals/data/omni-edu-v1",
            "--out",
            str(out),
            "--case",
            "omni-politics-008",
            "--preflight-only",
        ]
    )
    assert rc == 0
    assert fetched_channels == [None]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config_source"] == "admin:working-draft"
    assert manifest["config_id"] == "draft-19"
    assert manifest["config_revision"] == 19
    assert manifest["config_digest"] == sample["digest"]
    audit_snapshot = json.loads((out / "config-snapshot.json").read_text(encoding="utf-8"))
    assert audit_snapshot["digest"] == sample["digest"]


def test_platform_cli_allows_run_without_config_snapshot(monkeypatch):
    from types import SimpleNamespace

    from evals.platform import __main__ as platform_main

    seen: dict = {}

    monkeypatch.setattr(
        platform_main,
        "connect",
        lambda: (SimpleNamespace(shutdown=lambda: None), {}),
    )

    def fake_run(args, client, resources):
        seen["config_snapshot"] = args.config_snapshot
        seen["config_channel"] = args.config_channel
        return 0

    monkeypatch.setattr(platform_main, "run", fake_run)
    rc = platform_main.main(["run", "--config-channel", "release", "--case", "omni-politics-008"])
    assert rc == 0
    assert seen == {"config_snapshot": None, "config_channel": "release"}
