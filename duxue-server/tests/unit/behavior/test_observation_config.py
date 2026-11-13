import copy
import json
from pathlib import Path

import pytest

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.observation_contracts import provision, workflow_documents


def bundle():
    return json.loads(
        (Path(__file__).parents[2] / "fixtures/admin-release.json").read_text()
    )["bundle"]


def test_existing_release_is_still_accepted():
    original = bundle()
    compiled = compile_bundle(original)
    assert compiled.bundle == original


def test_optional_pair_is_atomic_and_uses_explicit_values():
    original = bundle()
    extended = copy.deepcopy(original)
    for identifier in ("behavior.visible-activity", "behavior.support-opportunity"):
        extended["files"][f"agents/{identifier}.json"] = provision(
            identifier, model="test-vlm", prompt="explicit test prompt"
        )
    extended["files"].update(workflow_documents())
    extended["compatibility"] = contract_compatibility(extended["files"])
    compiled = compile_bundle(extended)
    assert (
        compiled.catalog.units["behavior.visible-activity"].models[0].name == "test-vlm"
    )
    del extended["files"]["agents/behavior.support-opportunity.json"]
    with pytest.raises(ValueError):
        compile_bundle(extended)
