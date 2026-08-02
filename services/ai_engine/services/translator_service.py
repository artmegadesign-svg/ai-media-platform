import re
from services.ai_engine.services.ai_service import AIService


class AITranslatorService:
    def __init__(self):
        self.ai = AIService()

    def ru_to_en(self, text: str) -> str:
        system = "You are a professional translator."

        cleaned = self._clean(text)

        user = f"""
Translate from Russian to English.

Keep structure: HOOK / INSIGHT / VALUE / CONCLUSION

Text:
{cleaned}
"""

        return self.ai.chat(system, user)

    def _clean(self, text: str) -> str:
        lines = text.split("\n")
        return "\n".join(
            line for line in lines
            if not any(x in line for x in ["HOOK:", "INSIGHT:", "VALUE:", "CONCLUSION:"])
        ).strip()
