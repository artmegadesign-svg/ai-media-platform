from app.services.content_engine.generators.article_generator import ArticleGenerator
from app.services.content_engine.processors.quality_processor import QualityProcessor
from app.services.content_engine.builders.article_builder import ArticleBuilder


class ContentPipeline:
    """
    Full content generation pipeline.
    """

    def __init__(self):
        self.generator = ArticleGenerator()
        self.quality = QualityProcessor()
        self.builder = ArticleBuilder()

    def run(self, topic: str) -> dict:
        content = self.generator.generate(topic)

        checked_content = self.quality.process(
            content
        )

        article = self.builder.build(
            checked_content
        )

        return article
