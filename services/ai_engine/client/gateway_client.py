import httpx

from core.settings import settings


class GatewayClient:

    def chat(self, system: str, user: str) -> str:

        response = httpx.post(
            f"{settings.ai_gateway_url}/generate",
            json={
                "topic": user,
                "system": system,
                "user": user
            },
            timeout=60
        )

        response.raise_for_status()

        data = response.json()

        return data.get("ru_content") or data.get("en_content") or ""
