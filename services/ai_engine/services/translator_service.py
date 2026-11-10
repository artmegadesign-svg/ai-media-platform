from services.ai_engine.services.ai_service import AIService


class AITranslatorService:
    def __init__(self):
        self.ai = AIService()

    def ru_to_en(self, text: str) -> str:
        system = """You are a professional news translator for AI Digest.
Return only the finished English news item, 700–900 visible characters total.
Preserve the headline, facts, names, numbers, dates, URLs and their meaning.
Use plain text with short paragraphs, no Markdown, HTML or section labels.
Do not add facts, assistant phrases, offers of help or translation commentary.
"""
        # Editorial preparation belongs to ContentPipeline, for both languages.
        # Never drop an entire line merely because it contains a section label.
        return self.ai.chat(system, f"Translate this Russian news item to English:\n\n{text}")
