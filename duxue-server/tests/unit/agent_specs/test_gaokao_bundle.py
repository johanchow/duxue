import json
from pathlib import Path

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from scripts.upgrade_math_bundle import upgrade


def test_existing_admin_release_compatibility_fingerprint_unchanged():
    raw = json.loads(Path("tests/fixtures/admin-release.json").read_text(encoding="utf-8"))
    assert raw["bundle"]["compatibility"] == contract_compatibility(raw["bundle"]["files"])
    compiled = compile_bundle(raw["bundle"])
    assert compiled.digest == raw["digest"]


def test_upgrade_gaokao_bundle_compiles_with_blueprint_science_and_inspect_image():
    raw = json.loads(Path("tests/fixtures/admin-release.json").read_text(encoding="utf-8"))
    upgraded = upgrade(raw, enable=True, phase3=True, gaokao=True, enable_thinking=True, thinking_budget=4096)
    bundle = upgraded["bundle"]
    files = bundle["files"]
    assert "agents/tutoring.blueprint-planner.json" in files
    assert "tools/tutoring.science.json" in files
    assert "tools/tutoring.inspect_image.json" in files
    assert "tutoring.science" in files["agents/tutoring.turn.json"]["tools"]
    assert "tutoring.inspect_image" in files["agents/tutoring.turn.json"]["tools"]

    compiled = compile_bundle(bundle)
    assert compiled.digest == upgraded["digest"]
    assert "tutoring.blueprint-planner" in compiled.catalog.units
    assert "tutoring.stem-reread" in compiled.catalog.components


def test_upgrade_guardian_mentor_bundle_compiles_standalone_and_with_gaokao():
    raw = json.loads(Path("tests/fixtures/admin-release.json").read_text(encoding="utf-8"))
    standalone = upgrade(raw, guardian_mentor=True)
    assert "agents/tutoring.mentor-explain.json" in standalone["bundle"]["files"]
    assert "workflows/guardian-mentor.json" in standalone["bundle"]["files"]
    compiled_standalone = compile_bundle(standalone["bundle"])
    assert compiled_standalone.digest == standalone["digest"]
    assert "tutoring.mentor-explain" in compiled_standalone.catalog.units
    assert "tutoring.mentor-explain" in compiled_standalone.catalog.components

    combined = upgrade(raw, enable=True, phase3=True, gaokao=True, guardian_mentor=True, enable_thinking=True, thinking_budget=4096)
    compiled_combined = compile_bundle(combined["bundle"])
    assert compiled_combined.digest == combined["digest"]
    assert "tutoring.blueprint-planner" in compiled_combined.catalog.units
    assert "tutoring.mentor-explain" in compiled_combined.catalog.units
