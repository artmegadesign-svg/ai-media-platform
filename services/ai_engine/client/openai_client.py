from openai import OpenAI
from services.ai_engine.providers.openai_provider import OpenAIProvider


class OpenAIClient:
    def __init__(self):
        self.provider = OpenAIProvider()

    def chat(self, system: str, user: str) -> str:
        return self.provider.chat(system, user)
