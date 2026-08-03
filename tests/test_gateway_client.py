import importlib

import pytest


@pytest.fixture
def gateway_module(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_URL", "http://gateway.example:9000")
    monkeypatch.setenv("POSTGRES_DB", "ai_media")
    monkeypatch.setenv("POSTGRES_USER", "amp")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")

    import core.settings

    importlib.reload(core.settings)

    import services.ai_engine.client.gateway_client

    return importlib.reload(services.ai_engine.client.gateway_client)


def test_gateway_client_uses_configured_url_without_changing_generate_contract(
    gateway_module, monkeypatch
):
    recorded_request = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ru_content": "Русский текст", "en_content": "English text"}

    def fake_post(url, **kwargs):
        recorded_request["url"] = url
        recorded_request.update(kwargs)
        return Response()

    monkeypatch.setattr(gateway_module.httpx, "post", fake_post)

    result = gateway_module.GatewayClient().chat("system prompt", "topic")

    assert result == "Русский текст"
    assert recorded_request == {
        "url": "http://gateway.example:9000/generate",
        "json": {
            "topic": "topic",
            "system": "system prompt",
            "user": "topic",
        },
        "timeout": 60,
    }


def test_gateway_client_falls_back_to_english_content(gateway_module, monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ru_content": "", "en_content": "English text"}

    monkeypatch.setattr(gateway_module.httpx, "post", lambda *args, **kwargs: Response())

    assert gateway_module.GatewayClient().chat("system prompt", "topic") == "English text"
