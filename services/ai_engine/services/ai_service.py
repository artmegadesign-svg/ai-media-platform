from services.ai_engine.client.gateway_client import GatewayClient


class AIService:

    def __init__(self):
        self.client = GatewayClient()

    def chat(self, system: str, user: str) -> str:
        return self.client.chat(system, user)
