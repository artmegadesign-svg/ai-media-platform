from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from uuid import UUID, uuid4, uuid5

import httpx

from models.channel_content import ChannelContent
from services.publisher.interface import PublisherInterface
from services.publisher.media import PublicationMedia
from services.publisher.models import PublishResult


IDEMPOTENCY_NAMESPACE = UUID("7e69fe26-cf27-4c17-88aa-28fb13980254")
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_IMAGE_CAPTION_LIMIT = 1024
TRUNCATION_SUFFIX = "\n\n…"


class TelegramPublisher(PublisherInterface):
    """Publish Telegram content through the internal AI Gateway API."""

    def __init__(
        self,
        gateway_url: str,
        internal_token: str,
        gateway_channel_id: str,
        text: str,
        media: PublicationMedia | None = None,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ):
        self.gateway_url = gateway_url.rstrip("/")
        self.internal_token = internal_token
        self.gateway_channel_id = gateway_channel_id
        self.text = text
        self.media = media
        self.client = client
        self.timeout = timeout

    @staticmethod
    def idempotency_key(content: ChannelContent) -> str:
        if content.id is None:
            raise ValueError("ChannelContent must be persisted before publication")
        return str(uuid5(IDEMPOTENCY_NAMESPACE, f"channel-content:{content.id}"))

    @staticmethod
    def truncate_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> str:
        """Fit publication text within the applicable Telegram text limit."""
        if len(text) <= limit:
            return text

        content_limit = limit - len(TRUNCATION_SUFFIX)
        candidate = text[:content_limit]
        newline_index = candidate.rfind("\n")
        if newline_index != -1:
            candidate = candidate[:newline_index]

        return candidate + TRUNCATION_SUFFIX

    def publish(self, content: ChannelContent) -> PublishResult:
        url = f"{self.gateway_url}/api/v1/telegram/publications"
        headers = {
            "Authorization": f"Bearer {self.internal_token}",
            "Idempotency-Key": self.idempotency_key(content),
            "X-Request-ID": str(uuid4()),
        }
        text_limit = (
            TELEGRAM_IMAGE_CAPTION_LIMIT
            if self.media is not None
            else TELEGRAM_TEXT_LIMIT
        )
        payload = {
            "gateway_channel_id": self.gateway_channel_id,
            "text": self.truncate_text(self.text, text_limit),
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        if self.media is not None:
            payload["media"] = {
                "type": self.media.type,
                "url": self.media.url,
            }

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
        except httpx.TimeoutException:
            return PublishResult(success=False, error="AI Gateway request timed out")
        except httpx.TransportError:
            return PublishResult(success=False, error="AI Gateway transport error")

        if response.status_code >= 400:
            error = f"AI Gateway returned HTTP {response.status_code}"
            try:
                error_details = json.dumps(response.json(), ensure_ascii=False)
            except ValueError:
                error_details = response.text
            if error_details:
                error += f": {error_details}"

            retry_after = response.headers.get("Retry-After")
            if retry_after:
                error += f" (Retry-After: {retry_after})"
            return PublishResult(success=False, error=error)

        try:
            data = response.json()
        except ValueError:
            return PublishResult(
                success=False, error="AI Gateway returned invalid JSON"
            )

        external_message_id = data.get("external_message_id")
        if external_message_id is None or str(external_message_id).strip() == "":
            return PublishResult(
                success=False,
                error="AI Gateway response has no external_message_id",
            )

        published_at = datetime.now(timezone.utc)
        date_header = response.headers.get("Date")
        if date_header:
            try:
                published_at = parsedate_to_datetime(date_header)
            except (TypeError, ValueError):
                pass

        return PublishResult(
            success=True,
            platform_post_id=str(external_message_id),
            published_at=published_at,
        )
