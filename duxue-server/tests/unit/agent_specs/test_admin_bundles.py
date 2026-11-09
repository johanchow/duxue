import copy

import pytest


def test_bundle_checks_fixed_contracts_and_context_isolation():
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import snapshot_bundle
    from app.agent_specs.definitions import use_definitions
    from app.infrastructure.ai.components import COMPONENTS
    from app.infrastructure.ai.prompts import render_fragment

    original = COMPONENTS.get("tutoring.turn").prompt.text
    bundle = snapshot_bundle()
    changed = copy.deepcopy(bundle)
    changed["files"]["agents/tutoring.turn.json"]["prompt"]["template"] = "测试草稿正文"
    changed["files"]["agents/tutoring.turn.json"]["prompt"]["fragments"][
        "invalid_json"
    ]["template"] = "测试修复"
    compiled = compile_bundle(changed)
    with use_definitions(compiled.catalog):
        assert COMPONENTS.get("tutoring.turn").prompt.text == "测试草稿正文"
        assert render_fragment("tutoring.turn", "invalid_json") == "测试修复"
    assert COMPONENTS.get("tutoring.turn").prompt.text == original
    assert compile_bundle(bundle).digest != compiled.digest
    changed["files"]["agents/tutoring.turn.json"]["output_schema"] = {"type": "object"}
    with pytest.raises(ValueError, match="read-only"):
        compile_bundle(changed)


def test_bundle_rejects_compatibility_drift_unknown_files_and_tool_expansion():
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import snapshot_bundle

    bundle = snapshot_bundle()
    bundle["compatibility"] = "old-code"
    with pytest.raises(ValueError, match="compatibility"):
        compile_bundle(bundle)
    bundle = snapshot_bundle()
    bundle["files"]["../settings.py"] = {}
    with pytest.raises(ValueError):
        compile_bundle(bundle)

    bundle = snapshot_bundle()
    bundle["files"]["agents/tutoring.turn.json"]["tools"].append("unknown.tool")
    with pytest.raises(ValueError):
        compile_bundle(bundle)


def test_release_pin_retains_the_same_snapshot_during_replacement(tmp_path):
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import snapshot_bundle
    from app.agent_specs.release_runtime import ReleaseRuntime
    from app.infrastructure.ai.components import COMPONENTS

    runtime = ReleaseRuntime("http://unused", "secret", tmp_path / "last-good.json")
    first = snapshot_bundle()
    first["files"]["agents/tutoring.turn.json"]["prompt"]["template"] = "first"
    runtime.accept(
        {"id": "first", "digest": compile_bundle(first).digest, "bundle": first}
    )
    with runtime.pin():
        second = copy.deepcopy(first)
        second["files"]["agents/tutoring.turn.json"]["prompt"]["template"] = "second"
        runtime.accept(
            {"id": "second", "digest": compile_bundle(second).digest, "bundle": second}
        )
        assert COMPONENTS.get("tutoring.turn").prompt.text == "first"
    with runtime.pin():
        assert COMPONENTS.get("tutoring.turn").prompt.text == "second"

    corrupted = {"id": "corrupt", "digest": "wrong", "bundle": first}
    with pytest.raises(ValueError, match="digest"):
        runtime.accept(corrupted)
    with runtime.pin():
        assert COMPONENTS.get("tutoring.turn").prompt.text == "second"


def test_pull_failure_reports_error_and_retains_last_good_cache(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.agent_specs import release_runtime
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import snapshot_bundle
    from app.infrastructure.ai.components import COMPONENTS

    bundle = snapshot_bundle()
    bundle["files"]["agents/tutoring.turn.json"]["prompt"]["template"] = "last-good"
    cache = tmp_path / "last-good.json"
    runtime = release_runtime.ReleaseRuntime("http://unused", "secret", cache)
    runtime.accept(
        {"id": "good", "digest": compile_bundle(bundle).digest, "bundle": bundle}
    )
    acknowledgements = []
    monkeypatch.setattr(
        release_runtime.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "release": {"id": "bad", "digest": "wrong", "bundle": bundle}
            },
        ),
    )
    monkeypatch.setattr(
        release_runtime.httpx,
        "post",
        lambda *args, **kwargs: (
            acknowledgements.append(kwargs["json"])
            or SimpleNamespace(raise_for_status=lambda: None)
        ),
    )
    runtime.tick()
    assert acknowledgements[0]["status"] == "failed"
    assert acknowledgements[0]["release_id"] == "good"
    restored = release_runtime.ReleaseRuntime("http://unused", "secret", cache)
    monkeypatch.setattr(restored, "tick", lambda: None)
    restored.start()
    try:
        with restored.pin():
            assert COMPONENTS.get("tutoring.turn").prompt.text == "last-good"
    finally:
        restored.close()


def test_internal_admin_api_requires_secret_and_rejects_protocol_edits(
    client, monkeypatch
):
    from app.agent_specs.configuration import snapshot_bundle

    monkeypatch.setenv("AGENT_ADMIN_INTERNAL_TOKEN", "unit-test-secret")
    monkeypatch.setenv("APP_ENV", "test")
    assert client.get("/internal/agent-admin/catalog").status_code == 401
    headers = {"Authorization": "Bearer unit-test-secret"}
    bundle = snapshot_bundle()
    assert (
        client.post(
            "/internal/agent-admin/validate", headers=headers, json={"bundle": bundle}
        ).status_code
        == 200
    )
    bundle["files"]["gates/tutoring.leak-judge.json"]["on_error"] = "abort"
    assert (
        client.post(
            "/internal/agent-admin/validate", headers=headers, json={"bundle": bundle}
        ).status_code
        == 422
    )
    monkeypatch.setenv("APP_ENV", "production")
    assert (
        client.get("/internal/agent-admin/catalog", headers=headers).status_code == 403
    )


def test_debug_problem_reaches_tutor_and_judge_as_authorized_history(
    monkeypatch, capsys
):
    import io
    import json
    from types import SimpleNamespace

    from app.agent_specs import debug_worker
    from app.agent_specs.configuration import snapshot_bundle
    from app.bootstrap import settings as settings_module
    from app.infrastructure.ai import components, tutor_turn_model
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw

    problem = "小明有3盒彩笔，每盒4支，一共有多少支？"
    model = StaticTutorModel(tutor_raw("guide", "先想想每盒的数量是否相同。"))
    judge = StaticLeakJudge(False)
    monkeypatch.setattr(
        tutor_turn_model, "QwenTutorTurnGateway", lambda **kwargs: model
    )
    monkeypatch.setattr(tutor_turn_model, "QwenLeakJudge", lambda **kwargs: judge)
    monkeypatch.setattr(
        settings_module,
        "settings",
        SimpleNamespace(dashscope_api_key="unit-test", agent_model_timeout_seconds=8),
    )
    monkeypatch.setattr(components, "model_call_span", components.model_call_span)
    monkeypatch.setattr(
        components, "record_model_response", components.record_model_response
    )
    monkeypatch.setattr(
        debug_worker.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "bundle": snapshot_bundle(),
                    "input": {"content": "给我一个提示", "problem": problem},
                }
            )
        ),
    )
    debug_worker.main()
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "succeeded"
    assert model.calls[0]["recent_utterances"] == [{"author": "ward", "text": problem}]
    assert json.loads(judge.problems[0])["recent_problems"] == [problem]


def test_full_release_has_all_configuration_files_and_edits_all_model_agents():
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import snapshot_bundle
    from app.agent_specs.definitions import ROOT

    bundle = snapshot_bundle()
    assert bundle["format_version"] == 3
    assert set(bundle["files"]) == {
        str(path.relative_to(ROOT)) for path in ROOT.rglob("*.json")
    }
    bundle["files"]["agents/companion.intent.json"]["prompt"]["template"] += (
        "\n发布版本指令。"
    )
    bundle["files"]["agents/planning.intake.json"]["prompt"]["template"] += (
        "\n发布版本计划指令。"
    )
    bundle["files"]["agents/reflection.session-turn.json"]["display_name"] = (
        "已发布复盘执行器"
    )
    compiled = compile_bundle(bundle)
    assert "发布版本指令" in compiled.catalog.units["companion.intent"].prompt.template
    assert (
        compiled.catalog.code_agents["reflection.session-turn"].display_name
        == "已发布复盘执行器"
    )


def test_published_release_is_used_outside_tutoring_and_nested_pins_keep_same_version(
    tmp_path, monkeypatch
):
    from app.agent_specs import release_runtime
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import snapshot_bundle
    from app.application.commands.plan_intake import PlanIntakeInput, _prompt
    from app.infrastructure.ai.components import COMPONENTS

    runtime = release_runtime.ReleaseRuntime(
        "http://unused", "secret", tmp_path / "cache.json"
    )
    monkeypatch.setattr(release_runtime, "runtime", runtime)
    first = snapshot_bundle()
    first["files"]["agents/companion.intent.json"]["prompt"]["template"] += "\n版本A"
    first["files"]["agents/planning.intake.json"]["prompt"]["template"] += "\n计划A"
    runtime.accept({"id": "a", "digest": compile_bundle(first).digest, "bundle": first})
    assert "版本A" in COMPONENTS.get("companion.intent").prompt.text
    assert "计划A" in _prompt({}, [], PlanIntakeInput(content="安排作业"))
    with release_runtime.pin_release():
        second = copy.deepcopy(first)
        second["files"]["agents/companion.intent.json"]["prompt"]["template"] += (
            "\n版本B"
        )
        runtime.accept(
            {"id": "b", "digest": compile_bundle(second).digest, "bundle": second}
        )
        with release_runtime.pin_release():
            assert "版本B" not in COMPONENTS.get("companion.intent").prompt.text
    assert "版本B" in COMPONENTS.get("companion.intent").prompt.text


def test_admin_mode_does_not_silently_use_code_defaults(tmp_path, monkeypatch):
    from app.agent_specs import release_runtime
    from app.infrastructure.ai.components import COMPONENTS

    monkeypatch.setattr(
        release_runtime,
        "runtime",
        release_runtime.ReleaseRuntime("http://unused", "secret", tmp_path / "empty"),
    )
    with pytest.raises(release_runtime.AgentConfigurationUnavailable):
        COMPONENTS.get("companion.intent")


def test_complete_artifact_values_do_not_get_filled_from_changed_local_prompt(
    tmp_path, monkeypatch
):
    import json
    import shutil

    from app.agent_specs import admin_bundle
    from app.agent_specs.configuration import snapshot_bundle
    from app.agent_specs.definitions import ROOT

    original = snapshot_bundle()
    original["files"]["agents/companion.intent.json"]["prompt"]["template"] += (
        "\nAdmin产物"
    )
    shutil.copytree(ROOT, tmp_path / "specs")
    monkeypatch.setattr("app.agent_specs.definitions.ROOT", tmp_path / "specs")
    file = tmp_path / "specs/agents/companion.intent.json"
    local = json.loads(file.read_text())
    local["prompt"]["template"] += "\n本地不同正文"
    file.write_text(json.dumps(local))
    actual = admin_bundle.compile_bundle(original)
    assert "Admin产物" in actual.catalog.units["companion.intent"].prompt.template
    assert (
        "本地不同正文" not in actual.catalog.units["companion.intent"].prompt.template
    )


def test_generic_component_debug_uses_published_dynamic_prompt(monkeypatch, capsys):
    import io
    import json
    from types import SimpleNamespace

    from app.agent_specs import debug_worker
    from app.agent_specs.configuration import snapshot_bundle
    from app.bootstrap import settings as settings_module
    from app.infrastructure.ai import components

    bundle = snapshot_bundle()
    bundle["files"]["agents/task.intake.json"]["prompt"]["template"] += (
        "\nAdmin任务配置"
    )
    variables = bundle["files"]["agents/task.intake.json"]["prompt"]["variables"]
    context = {
        name: []
        if definition["type"] == "array"
        else {}
        if definition["type"] == "object"
        else ""
        for name, definition in variables.items()
    }
    captured = []

    def fake_model(**kwargs):
        captured.append(kwargs)
        return {
            "tasks": [],
            "assistant_text": "需要补充任务",
            "clarification_required": True,
        }

    monkeypatch.setattr(components, "invoke_json_component", fake_model)
    monkeypatch.setattr(components, "model_call_span", components.model_call_span)
    monkeypatch.setattr(
        components, "record_model_response", components.record_model_response
    )
    monkeypatch.setattr(
        settings_module,
        "settings",
        SimpleNamespace(dashscope_api_key="unit-test", agent_model_timeout_seconds=8),
    )
    monkeypatch.setattr(
        debug_worker.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "bundle": bundle,
                    "input": {
                        "component_id": "task.intake",
                        "content": json.dumps(context),
                    },
                }
            )
        ),
    )
    debug_worker.main()
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "succeeded"
    assert result["covered_units"] == ["task.intake"]
    assert "Admin任务配置" in captured[0]["user"]


def test_reused_backup_gateway_resolves_each_pinned_artifact(monkeypatch):
    from types import SimpleNamespace

    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import snapshot_bundle
    from app.agent_specs.definitions import use_definitions
    from app.infrastructure.ai import components
    from app.infrastructure.ai.tutor_turn_model import QwenTutorTurnGateway

    captured = []

    def invoke(**kwargs):
        captured.append(kwargs["spec"].model)
        return SimpleNamespace(unwrap=dict)

    monkeypatch.setattr(components, "invoke_agent_component", invoke)
    gateway = QwenTutorTurnGateway(component_id="tutoring.turn-backup")
    for name in ["backup-a", "backup-b"]:
        bundle = snapshot_bundle()
        bundle["files"]["agents/tutoring.turn.json"]["models"][1]["name"] = name
        with use_definitions(compile_bundle(bundle).catalog):
            gateway.complete(envelope={}, instruction="test")
    assert captured == ["backup-a", "backup-b"]


def test_artifact_identity_and_compatibility_ignore_legacy_definition_versions(
    tmp_path, monkeypatch
):
    import json
    import shutil

    from app.agent_specs import admin_bundle
    from app.agent_specs.configuration import snapshot_bundle
    from app.agent_specs.definitions import ROOT

    original = snapshot_bundle()
    assert original["format_version"] == 3
    for doc in original["files"].values():
        assert "version" not in doc
        assert all("version" not in model for model in doc.get("models", []))
    shutil.copytree(ROOT, tmp_path / "specs")
    monkeypatch.setattr("app.agent_specs.definitions.ROOT", tmp_path / "specs")
    path = tmp_path / "specs/agents/companion.intent.json"
    doc = json.loads(path.read_text())
    doc["version"] = "v999"
    doc["prompt"]["id"] = "legacy-version-changed"
    path.write_text(json.dumps(doc))
    assert snapshot_bundle()["compatibility"] == original["compatibility"]
    compiled = admin_bundle.compile_bundle(original)
    assert compiled.catalog.units["companion.intent"].version == compiled.digest
    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.definitions import use_definitions

    with use_definitions(compiled.catalog):
        assert (
            load_catalog().component_identity("companion.intent").unit_version
            == compiled.digest
        )
