import pytest

from core.settings import settings
from services.intelligence.factory import (
    create_intelligence_content_generation_service,
)
from services.media.adapters.ai_gateway import AIGatewayImageGenerationProvider


def test_production_composition_injects_ai_gateway_image_provider(monkeypatch):
    monkeypatch.setattr(settings, "ai_gateway_url", "https://gateway.example")
    monkeypatch.setattr(settings, "ai_gateway_internal_token", "test-token")

    service = create_intelligence_content_generation_service()

    assert isinstance(service.image_provider, AIGatewayImageGenerationProvider)
    assert service.image_provider.gateway_url == "https://gateway.example"


def test_production_composition_fails_explicitly_without_gateway_token(monkeypatch):
    monkeypatch.setattr(settings, "ai_gateway_internal_token", None)

    with pytest.raises(ValueError, match="internal token is not configured"):
        create_intelligence_content_generation_service()
