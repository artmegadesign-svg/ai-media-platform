import os
from services.ai_engine.providers.mock_provider import MockProvider

class OpenAIProvider:
    def __init__(self):
        self.mode = os.getenv("AI_MODE", "mock")  # mock | openai

        self.mock = MockProvider()

        if self.mode == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def chat(self, system: str, user: str) -> str:
        if self.mode == "mock":
            return self.mock.chat(system, user)

        return self._openai_chat(system, user)

    def _openai_chat(self, system: str, user: str) -> str:
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

        return response.choices[0].message.content
