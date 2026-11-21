import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.debug_contracts import debug_capabilities
from app.agent_specs.definitions import use_definitions
from app.agent_specs.execution_trace import Recorder
from app.application.workflows import guardian_mentor as mentor
from app.infrastructure.ai.errors import ModelGatewayError, ModelTimeBudgetExceeded
from scripts.upgrade_blueprint_steps import upgrade as stage_blueprint
from scripts.upgrade_guardian_mentor_review import upgrade
from scripts.upgrade_math_bundle import upgrade as provision


@pytest.fixture(scope="module")
def releases():
    source = json.loads(Path("tests/fixtures/admin-release.json").read_text())
    old = stage_blueprint(provision(source, guardian_mentor=True, gaokao=True))
    new = upgrade(old, parent=True)
    assert new["digest"] == upgrade(new, parent=True)["digest"]
    assert [path for path, value in new["bundle"]["files"].items()
            if old["bundle"]["files"][path] != value] == ["workflows/guardian-mentor.json"]
    assert "guardian-mentor" in debug_capabilities(compile_bundle(new["bundle"]).catalog)["workflows"]
    return old, new


def test_compiler_rejects_skipped_blueprint(releases):
    bundle = deepcopy(releases[1]["bundle"])
    graph = bundle["files"]["workflows/guardian-mentor.json"]
    graph["edges"].append({"from": "guardian-mentor.prepare", "to": "guardian-mentor.explain"})
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    with pytest.raises(ValueError, match="guardian mentor parent topology"):
        compile_bundle(bundle)


@pytest.mark.parametrize(("case", "calls", "act"), [
    ("ok", 1, "explain"), ("retry", 2, "explain"), ("invalid", 2, "unavailable"),
    ("transport", 1, "unavailable"), ("unsafe_output", 1, "safety"),
    ("unsafe_input", 0, "safety"), ("ambiguous", 0, "clarify"), ("deadline", 1, "timeout"),
])
def test_turn_matches_legacy_and_records_child(releases, case, calls, act, monkeypatch):
    from app.application.workflows.guardian_experience import experience_turn
    from app.infrastructure.security.experience_tokens import unseal

    monkeypatch.setattr(mentor.LocalSafetyScreening, "blocks_input", lambda self, **kw: case == "unsafe_input")
    monkeypatch.setattr(mentor.LocalSafetyScreening, "blocks_output", lambda self, **kw: case == "unsafe_output")
    monkeypatch.setattr("app.application.workflows.guardian_experience._image", lambda *args: None)
    comparable = []
    for record in releases:
        solver = Mock()
        solver.extract_stem.return_value = {"tier": "T1", "raw_text": "原题"}
        solver.solve_route.return_value = {"final_answers": {"main": "3"}}
        monkeypatch.setattr(mentor, "QwenProblemSolverGateway", lambda settings: solver)
        response = {"content": "完整解析", "act": "explain"}
        invalid = ModelGatewayError("invalid_model_candidate")
        responses = {"retry": [invalid, response], "invalid": [invalid, invalid],
                     "transport": [ModelGatewayError("model_transport_error")],
                     "deadline": [ModelTimeBudgetExceeded()]}
        gateway = Mock()
        gateway.explain.side_effect = responses.get(case, [response])
        monkeypatch.setattr(mentor, "QwenMentorExplainGateway", lambda settings: gateway)
        recording = Recorder()
        with use_definitions(compile_bundle(record["bundle"]).catalog), recording.capture():
            try:
                result = experience_turn(
                    guardian_id="parent-" + case, content="请讲解", attachment_keys=["missing"] if case == "ambiguous" else [],
                    state={}, mode="guardian_explain",
                )
            except ModelTimeBudgetExceeded:
                result = {"act": "timeout"}
        assert result["act"] == act
        assert gateway.explain.call_count == calls
        assert solver.extract_stem.call_count == int(calls > 0)
        assert solver.solve_route.call_count == int(calls > 0)
        if "state_token" in result:
            state = unseal(result.pop("state_token"), "parent-" + case, mentor.MENTOR_PURPOSE)
            comparable.append((result, [row["text"] for row in state["window"]]))
        if record is releases[1]:
            nodes = [e for e in recording.events if e.get("workflow_id") == "guardian-mentor" and e.get("node_id")]
            assert nodes[0]["node_id"] == "guardian-mentor.prepare"
            if calls:
                child = next(e for e in nodes if e["node_id"] == "guardian-mentor.blueprint")
                assert any(e.get("workflow_id") == "tutoring-blueprint" and e["parent_id"] == child["id"]
                           for e in recording.events)
            assert sum(e["node_id"] == "guardian-mentor.explain" for e in nodes) == calls
    if comparable:
        assert comparable[0] == comparable[1]


def test_http_turn_obeys_parent_retry_budget(client, db, releases, monkeypatch):
    from app.infrastructure.persistence.models import Guardian, User, uid
    from app.infrastructure.security.tokens import create_access_token

    identifier = uid()
    db.add(User(id=identifier, type="guardian"))
    db.flush()
    db.add(Guardian(id=identifier, name="Parent", email="mentor-parent@example.com", role="guardian"))
    db.commit()
    bundle = deepcopy(releases[1]["bundle"])
    bundle["files"]["workflows/guardian-mentor.json"]["limits"]["model_calls"] = 1
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    gateway = Mock(side_effect=ModelGatewayError("invalid_model_candidate"))
    monkeypatch.setattr(mentor.QwenMentorExplainGateway, "explain", gateway)
    monkeypatch.setattr(mentor.QwenProblemSolverGateway, "extract_stem", lambda *a, **kw: {"tier": "T0"})
    with use_definitions(compile_bundle(bundle).catalog):
        result = client.post("/guardian/experience/turn", headers={
            "Authorization": f"Bearer {create_access_token(user_id=identifier, role='guardian')}",
        }, json={"content": "解释一个概念", "mode": "guardian_explain"})
    assert result.status_code == 200
    assert result.json()["act"] == "unavailable"
    assert gateway.call_count == 1
