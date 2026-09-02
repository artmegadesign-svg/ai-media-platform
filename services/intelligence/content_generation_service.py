"""Bridge approved intelligence results into the existing Content Engine."""

from collections.abc import Iterable
from typing import Protocol

from services.ai_engine.services.generator_service import GeneratorService
from services.intelligence.models import IntelligenceResult


class GeneratorServiceProtocol(Protocol):
    def generate(self, topic: str) -> dict: ...


class IntelligenceContentGenerationService:
    """Generate content once for each approved intelligence result."""

    def __init__(self, generator: GeneratorServiceProtocol | None = None) -> None:
        self.generator = generator if generator is not None else GeneratorService()

    def generate(self, results: Iterable[IntelligenceResult]) -> list[dict]:
        """Pass normalized news headlines to the existing generation entry point."""
        generated = []
        for result in results:
            if not result.publish:
                continue

            topic = result.news.title.strip()
            if not topic:
                continue

            generated.append(self.generator.generate(topic))

        return generated
