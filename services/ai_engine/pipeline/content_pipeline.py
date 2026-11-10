import re

from services.ai_engine.services.writer_service import AIWriterService
from services.ai_engine.services.translator_service import AITranslatorService
from services.ai_engine.services.post_service import PostService
from services.ai_engine.agents.quality_agent import QualityAgent
from services.ai_engine.agents.strategy_agent import StrategyAgent
from services.news.normalizer import source_identity

class ContentPipeline:

    def __init__(self):
        self.strategy = StrategyAgent()
        self.writer = AIWriterService()
        self.translator = AITranslatorService()
        self.quality = QualityAgent()
        self.storage = PostService()

    def generate_full_content(self, topic: str, *, source_url: str | None = None):

        if source_url is not None:
            canonical_url, key = source_identity(source_url)
            existing = self.storage.find_by_source_key(key)
            if existing is not None:
                return self.storage.duplicate_result(existing, canonical_url)

        strategy_result = self.strategy.analyze(topic)

        enhanced_topic = f"""
Topic: {strategy_result.get('topic')}

Audience: {strategy_result.get('audience')}

Keywords: {', '.join(strategy_result.get('keywords', []))}
"""

        ru = self.prepare_text(self.writer.generate_ru(enhanced_topic))
        en = self.prepare_text(self.translator.ru_to_en(ru))
        checks = [self.quality.check(ru), self.quality.check(en)]
        checks = [check or {"score": 0, "approved": False,
                            "issues": ["Quality check returned empty result"]} for check in checks]
        quality_result = {
            "score": min(check.get("score", 0) for check in checks),
            "approved": all(check.get("approved", False) for check in checks),
            "issues": [f"{language}: {issue}" for language, check in zip(("RU", "EN"), checks)
                       for issue in (check.get("issues") or [])],
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
            quality_result,
            source_url=source_url,
        )

        if not post["post_created"]:
            return post

        return {
            "post_created": True,
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

    @staticmethod
    def prepare_text(text: str) -> str:
        """Normalize unambiguous presentation wrappers, never cut sentences/facts.

        Assistant prose and unsupported markup are left for Quality to reject.
        Only known whole labels/prefixes and balanced bold wrappers are removed.
        """
        if not isinstance(text, str):
            return ""
        lines = text.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n")
        if (len(lines) >= 2 and re.fullmatch(r"```(?:text|plaintext|markdown)?", lines[0].strip(), re.I)
                and lines[-1].strip() == "```"):
            lines = lines[1:-1]
        prepared = []
        section = QualityAgent.SERVICE_SECTION_PATTERN
        for line in lines:
            line = line.strip()
            line = re.sub(r"^#{1,6}\s+", "", line)
            line = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", line)
            if re.fullmatch(section + r"\s*:?\s*", line, re.I):
                continue
            line = re.sub(r"^" + section + r"\s*:\s*", "", line, flags=re.I)
            prepared.append(line)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(prepared)).strip()
