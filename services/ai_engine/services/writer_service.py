from services.ai_engine.services.ai_service import AIService
from services.ai_engine.prompts.writer_prompt import get_writer_system_prompt


class AIWriterService:
    def __init__(self):
        self.ai = AIService()

    def generate_ru(self, topic: str) -> str:
        system = get_writer_system_prompt()

        clean_topic = topic.replace("Topic:", "").replace("Topic", "").strip()

        user = f"""
Write a high-quality post in Russian about:
Topic: {clean_topic}

Format:
- Hook
- Insight
- Value
- Conclusion
"""

        return self.ai.chat(system, user)
