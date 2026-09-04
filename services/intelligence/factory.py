"""Production composition for intelligence content and media generation."""

from core.settings import settings
from services.intelligence.content_generation_service import (
    IntelligenceContentGenerationService,
)
from services.media.adapters.ai_gateway import AIGatewayImageGenerationProvider


def create_intelligence_content_generation_service() -> (
    IntelligenceContentGenerationService
):
    """Build the production bridge without starting or scheduling any work."""
    image_provider = AIGatewayImageGenerationProvider(
        gateway_url=settings.ai_gateway_url,
        internal_token=settings.ai_gateway_internal_token,
    )
    return IntelligenceContentGenerationService(image_provider=image_provider)
