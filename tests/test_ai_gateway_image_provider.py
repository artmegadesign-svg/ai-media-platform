import json

import httpx
import pytest

from services.media.adapters.ai_gateway import (
    AIGatewayImageGenerationError,
    AIGatewayImageGenerationProvider,
)


def _provider(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return AIGatewayImageGenerationProvider(
        gateway_url="https://gateway.example/base/",
        internal_token="internal-secret",
        client=client,
        timeout=12.0,
    )


def test_image_generation_request_contract_and_response_mapping():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "url": "https://cdn.example/generated/image.jpg",
                "thumbnail_url": "https://cdn.example/generated/thumb.jpg",
                "provider": "timeweb",
                "metadata": {"request_id": "req-1"},
            },
        )

    result = _provider(handler).generate(
        prompt="Editorial illustration", language_code="ru"
    )

    assert requests[0].url == httpx.URL(
        "https://gateway.example/base/api/v1/images/generations"
    )
    assert requests[0].headers["Authorization"] == "Bearer internal-secret"
    assert json.loads(requests[0].content) == {
        "prompt": "Editorial illustration",
        "language_code": "ru",
    }
    assert result.url == "https://cdn.example/generated/image.jpg"
    assert result.thumbnail_url == "https://cdn.example/generated/thumb.jpg"
    assert result.provider == "timeweb"
    assert result.metadata == {"request_id": "req-1"}


@pytest.mark.parametrize(
    ("exception", "message"),
    [
        (httpx.ReadTimeout("secret detail"), "AI Gateway image request timed out"),
        (httpx.ConnectError("secret detail"), "AI Gateway image transport error"),
    ],
)
def test_image_generation_maps_network_failures(exception, message):
    def handler(request):
        raise exception

    with pytest.raises(AIGatewayImageGenerationError, match=f"^{message}$"):
        _provider(handler).generate(prompt="Prompt", language_code=None)


def test_image_generation_maps_non_success_without_exposing_response():
    provider = _provider(
        lambda request: httpx.Response(503, json={"detail": "sensitive upstream"})
    )

    with pytest.raises(
        AIGatewayImageGenerationError,
        match="^AI Gateway image request returned HTTP 503$",
    ):
        provider.generate(prompt="Prompt", language_code="en")


def test_image_generation_rejects_invalid_json():
    provider = _provider(lambda request: httpx.Response(200, content=b"not-json"))

    with pytest.raises(
        AIGatewayImageGenerationError,
        match="^AI Gateway image response contained invalid JSON$",
    ):
        provider.generate(prompt="Prompt", language_code=None)


@pytest.mark.parametrize(
    "payload",
    [
        {"provider": "timeweb", "metadata": {}},
        {"url": "", "provider": "timeweb", "metadata": {}},
        {"url": "data:image/png;base64,AAAA", "provider": "timeweb", "metadata": {}},
        {"url": "http://cdn.example/image.jpg", "provider": "timeweb", "metadata": {}},
        {"url": "https:///missing-host.jpg", "provider": "timeweb", "metadata": {}},
    ],
)
def test_image_generation_rejects_missing_or_malformed_url(payload):
    provider = _provider(lambda request: httpx.Response(200, json=payload))

    with pytest.raises(
        AIGatewayImageGenerationError,
        match="^AI Gateway image response has an invalid URL$",
    ):
        provider.generate(prompt="Prompt", language_code=None)


def test_image_generation_requires_configured_token():
    with pytest.raises(ValueError, match="internal token is not configured"):
        AIGatewayImageGenerationProvider(
            gateway_url="https://gateway.example", internal_token=None
        )
