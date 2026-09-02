from services.ai_engine.services.writer_service import AIWriterService
from services.ai_engine.services.translator_service import AITranslatorService
from services.ai_engine.services.post_service import PostService
from services.ai_engine.agents.quality_agent import QualityAgent
from services.ai_engine.agents.strategy_agent import StrategyAgent

class ContentPipeline:

    def __init__(self):
        self.strategy = StrategyAgent()
        self.writer = AIWriterService()
        self.translator = AITranslatorService()
        self.quality = QualityAgent()
        self.storage = PostService()

    def generate_full_content(self, topic: str):

        strategy_result = self.strategy.analyze(topic)

        enhanced_topic = f"""
Topic: {strategy_result.get('topic')}

Audience: {strategy_result.get('audience')}

Angle: {strategy_result.get('angle')}

Content type: {strategy_result.get('content_type')}

Priority: {strategy_result.get('priority')}

Keywords: {', '.join(strategy_result.get('keywords', []))}
"""

        ru = self.writer.generate_ru(enhanced_topic)

        en = self.translator.ru_to_en(ru)

        quality_result = self.quality.check(ru)

        if not quality_result:
            quality_result = {
                "score": 0,
                "approved": False,
                "issues": ["Quality check returned empty result"]
            }

        if not quality_result.get("approved", False):
            return {
                "status": "rejected",
                "issues": quality_result.get("issues", []),
                "ru": ru,
                "en": en,
                "quality_score": quality_result.get("score"),
                "quality_approved": False,
                "quality_issues": quality_result.get("issues")
            }

        post = self.storage.save(
            topic,
            ru,
            en,
            quality_result
        )

        return {
            "status": "published",
            "id": post["id"],
            "title": post["title"],
            "topic": post["topic"],
            "ru": post["ru_content"],
            "en": post["en_content"],
            "quality_score": post["quality_score"],
            "quality_approved": post["quality_approved"],
            "quality_issues": post["quality_issues"]
        }
