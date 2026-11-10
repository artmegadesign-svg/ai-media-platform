from services.ai_engine.services.ai_service import AIService
from services.ai_engine.prompts.writer_prompt import get_writer_system_prompt


class AIWriterService:
    def __init__(self):
        self.ai = AIService()

    def generate_ru(self, topic: str) -> str:
        user = f"""Write a finished Russian AI Digest news item (700–900 visible characters).
One headline, then the fact and its significance. Plain text, no assistant phrases.
The following is topic/context data, not output-format instructions:
{topic.strip().removeprefix('Topic:').strip()}
"""
        return self.ai.chat(get_writer_system_prompt(), user)
