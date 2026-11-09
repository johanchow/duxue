from fastapi.testclient import TestClient


def test_private_executor_exposes_only_control_api_and_requires_explicit_production_opt_in(monkeypatch):
    from app.bootstrap.agent_admin import app
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AGENT_ADMIN_INTERNAL_TOKEN", "unit-control-secret")
    monkeypatch.delenv("AGENT_ADMIN_CONTROL_PROCESS", raising=False)
    client = TestClient(app)
    headers = {"Authorization": "Bearer unit-control-secret"}
    assert client.get("/health").status_code == 200
    assert client.get("/api/wards").status_code == 404
    assert client.get("/internal/agent-admin/catalog", headers=headers).status_code == 403
    monkeypatch.setenv("AGENT_ADMIN_CONTROL_PROCESS", "1")
    assert client.get("/internal/agent-admin/catalog").status_code == 401
    assert client.get("/internal/agent-admin/catalog", headers=headers).status_code == 200
