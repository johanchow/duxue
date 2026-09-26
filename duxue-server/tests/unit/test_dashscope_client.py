from __future__ import annotations

from app.infrastructure.ai.client import dashscope_client


def test_dashscope_client_ignores_ambient_proxy(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7897")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7897")

    client = dashscope_client()
    try:
        assert client._client.trust_env is False
    finally:
        client.close()
