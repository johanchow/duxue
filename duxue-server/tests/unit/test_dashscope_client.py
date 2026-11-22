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


def test_transport_observation_counts_attempts_without_recording_request_data():
    import httpx

    from app.infrastructure.ai.client import observe_transport

    observation = {}
    with dashscope_client(timeout=12) as client, observe_transport(observation):
        request = httpx.Request("POST", "https://example.invalid", extensions={"timeout": {"read": 12}})
        for hook in client._client.event_hooks["request"]:
            hook(request)
            hook(request)
        response = httpx.Response(200, request=request)
        for hook in client._client.event_hooks["response"]:
            hook(response)
    assert observation["http_attempts"] == 2
    assert observation["read_timeout_seconds"] == 12
    assert observation["response_headers_ms"] >= 0
