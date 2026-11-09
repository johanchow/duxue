"""Inventory exposes real definitions and exact workflow topology."""


def test_catalog_exposes_all_agents_and_workflows(client, monkeypatch):
    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.definitions import base_definitions

    monkeypatch.setenv("AGENT_ADMIN_INTERNAL_TOKEN", "inventory-test")
    monkeypatch.setenv("APP_ENV", "test")
    response = client.get(
        "/internal/agent-admin/catalog",
        headers={"Authorization": "Bearer inventory-test"},
    )
    assert response.status_code == 200
    data = response.json()
    definitions = base_definitions()
    expected = {u.id for u in definitions.units.values() if u.kind == "agent"} | set(
        definitions.code_agents
    )
    assert {a["id"] for a in data["agents"]} == expected
    assert data["counts"]["agents"] == len(expected)
    assert data["counts"]["model_agents"] + data["counts"]["code_agents"] == len(
        expected
    )
    assert set(data["workflows"]) == set(load_catalog().specs)
    for agent in data["agents"]:
        assert agent["name"] and agent["description"] and agent["workflows"]
        assert data["definitions"][agent["id"]]["id"] == agent["id"]
        for workflow_id in agent["workflows"]:
            workflow = data["workflows"][workflow_id]
            assert workflow["invocation_agent"] == agent["id"] or any(
                n["ref"] == agent["id"] for n in workflow["nodes"]
            )
    for key, workflow in data["workflows"].items():
        from app.agent_specs.admin_bundle import _artifact_document

        assert workflow == _artifact_document(
            load_catalog().spec(key).model_dump(mode="json", by_alias=True)
        )
    assert data["source"] == "code-baseline"
    assert data["counts"]["gates"] == len(definitions.code_gates) + sum(
        u.kind == "gate" for u in definitions.units.values()
    )


def test_inventory_includes_gate_and_tool_types_and_workflow_descriptions():
    from app.agent_specs.inventory import management_inventory

    data = management_inventory()
    assert {item["id"] for item in data["components"]} == set(data["definitions"])
    assert len(data["components"]) == data["counts"]["components"]
    assert (
        len([item for item in data["components"] if item["kind"] == "gate"])
        == data["counts"]["gates"]
    )
    assert set(data["workflow_descriptions"]) == set(data["workflows"])
    assert all(data["workflow_descriptions"].values())
    components = {item["id"]: item for item in data["components"]}
    assert components["tutoring.leak-judge"]["type"] == "model-judge"
    assert components["tutoring.leak-judge"]["editable"] is True
    assert components["tutoring.widget_guidelines"]["editable"] is True
    assert components["tutoring.get_task_context"]["editable"] is True
    assert components["tutoring.get_task_context"]["editable_fields"] == [
        "display_name",
        "description",
    ]
    for item in data["components"]:
        assert item["description"] and item["name"] and item["type"]
