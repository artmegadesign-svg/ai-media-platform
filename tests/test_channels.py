from datetime import datetime

import pytest
from pydantic import ValidationError

from app.routes import channels as channels_route
from models.channel import Channel
from schemas.channel import ChannelCreate, ChannelResponse
from services import channel_service as channel_service_module
from services.channel_service import ChannelService


class FakeRepository:
    def __init__(self, db):
        self.db = db
        self.created = None

    def create(self, channel):
        self.created = channel
        channel.id = 1
        channel.created_at = datetime(2026, 8, 4)
        return channel


def test_create_telegram_channel_with_gateway_channel_id(monkeypatch):
    monkeypatch.setattr(channel_service_module, "ChannelRepository", FakeRepository)
    service = ChannelService(db=object())

    channel = service.create_channel(
        name="AI Digest",
        platform="telegram",
        language_code="ru",
        gateway_channel_id="ai_digest",
        is_active=True,
    )

    assert channel.gateway_channel_id == "ai_digest"
    assert channel.is_active is True


def test_channel_endpoint_passes_gateway_id_and_returns_it(monkeypatch):
    captured = {}
    created_at = datetime(2026, 8, 4)

    class FakeService:
        def __init__(self, db):
            captured["db"] = db

        def create_channel(self, **kwargs):
            captured.update(kwargs)
            return Channel(id=7, created_at=created_at, **kwargs)

    monkeypatch.setattr(channels_route, "ChannelService", FakeService)
    data = ChannelCreate(
        name="AI Digest",
        platform="telegram",
        language_code="ru",
        gateway_channel_id="ai_digest",
        is_active=True,
    )

    result = channels_route.create_channel(data=data, db=object())
    response = ChannelResponse.model_validate(result)

    assert captured["gateway_channel_id"] == "ai_digest"
    assert response.gateway_channel_id == "ai_digest"


def test_legacy_youtube_channel_does_not_require_gateway_channel_id():
    data = ChannelCreate(
        name="YouTube RU",
        platform="youtube",
        language_code="ru",
    )

    assert data.gateway_channel_id is None
    assert data.is_active is True


@pytest.mark.parametrize("gateway_channel_id", [None, "", "   "])
def test_telegram_channel_requires_gateway_channel_id(gateway_channel_id):
    with pytest.raises(
        ValidationError,
        match="gateway_channel_id is required for Telegram channels",
    ):
        ChannelCreate(
            name="Invalid Telegram",
            platform="telegram",
            language_code="ru",
            gateway_channel_id=gateway_channel_id,
        )
