"""AI Gateway adapter for generated images."""

from typing import Any, cast
from urllib.parse import urlparse

import httpx

from services.media.generation_service import GeneratedMedia, MediaGenerationError


class AIGatewayImageGenerationError(MediaGenerationError):
    """Safe failure raised when AI Gateway cannot provide valid generated media."""


class AIGatewayImageGenerationProvider:
    """Generate images through the platform's authenticated internal gateway."""

    def __init__(
        self,
        *,
        gateway_url: str,
        internal_token: str | None,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not isinstance(gateway_url, str) or not gateway_url.strip():
            raise ValueError("AI Gateway URL is not configured")
        if not isinstance(internal_token, str) or not internal_token.strip():
            raise ValueError("AI Gateway internal token is not configured")
        if timeout <= 0:
            raise ValueError("AI Gateway timeout must be positive")

        self.gateway_url = gateway_url.rstrip("/")
        self._internal_token = internal_token
        self.client = client
        self.timeout = timeout

    def generate(self, *, prompt: str, language_code: str | None) -> GeneratedMedia:
        url = f"{self.gateway_url}/api/v1/images/generations"
        headers = {"Authorization": f"Bearer {self._internal_token}"}
        payload = {"prompt": prompt, "language_code": language_code}

        try:
            if self.client is None:
                response = httpx.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
            else:
                response = self.client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
        except httpx.TimeoutException as exc:
            raise AIGatewayImageGenerationError(
                "AI Gateway image request timed out"
            ) from exc
        except httpx.TransportError as exc:
            raise AIGatewayImageGenerationError(
                "AI Gateway image transport error"
            ) from exc

        if not response.is_success:
            raise AIGatewayImageGenerationError(
                f"AI Gateway image request returned HTTP {response.status_code}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AIGatewayImageGenerationError(
                "AI Gateway image response contained invalid JSON"
            ) from exc

        return self._map_response(data)

    @classmethod
    def _map_response(cls, data: Any) -> GeneratedMedia:
        if not isinstance(data, dict):
            raise AIGatewayImageGenerationError(
                "AI Gateway image response must be an object"
            )

        url = data.get("url")
        if not cls._is_public_https_url(url):
            raise AIGatewayImageGenerationError(
                "AI Gateway image response has an invalid URL"
            )

        thumbnail_url = data.get("thumbnail_url")
        if thumbnail_url is not None and not cls._is_public_https_url(thumbnail_url):
            raise AIGatewayImageGenerationError(
                "AI Gateway image response has an invalid thumbnail URL"
            )

        provider = data.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            raise AIGatewayImageGenerationError(
                "AI Gateway image response has an invalid provider"
            )

        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            raise AIGatewayImageGenerationError(
                "AI Gateway image response has invalid metadata"
            )

        return GeneratedMedia(
            url=cast(str, url),
            thumbnail_url=cast(str | None, thumbnail_url),
            provider=provider,
            metadata=metadata,
        )

    @staticmethod
    def _is_public_https_url(value: Any) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        parsed = urlparse(value)
        return parsed.scheme == "https" and bool(parsed.netloc)
