from app.services.content_engine.generators.base_generator import BaseGenerator
from app.services.ai_engine.services.generator_service import GeneratorService


class ArticleGenerator(BaseGenerator):
    """
    Generates media articles through AI Gateway.
    """

    def __init__(self):
        self.ai_service = GeneratorService()

    def generate(self, topic: str) -> dict:
        result = self.ai_service.generate(topic)

        return {
            "topic": topic,
            "ru_content": result.get("ru_content"),
            "en_content": result.get("en_content"),
            "source": "ai_gateway",
        }
