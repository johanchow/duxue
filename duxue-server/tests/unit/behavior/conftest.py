import pytest

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.definitions import use_definitions
from app.agent_specs.observation_contracts import IDS, provision, workflow_documents
from tests.unit.behavior.test_observation_config import bundle


@pytest.fixture(autouse=True)
def observation_release():
    record = bundle()
    for identifier in IDS:
        record["files"][f"agents/{identifier}.json"] = provision(
            identifier, model="test-vlm", prompt="explicit test prompt"
        )
    record["files"].update(workflow_documents())
    record["compatibility"] = contract_compatibility(record["files"])
    compiled = compile_bundle(record)
    with use_definitions(compiled.catalog):
        yield compiled
