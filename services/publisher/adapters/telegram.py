from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import re
from html import escape
from uuid import UUID, uuid4, uuid5

import httpx

from services.publisher.telegram_formatting import render_news
from services.publisher.interface import PublisherInterface
from services.publisher.media import PublicationMedia
from services.publisher.models import PublicationReference, PublishResult


IDEMPOTENCY_NAMESPACE = UUID("7e69fe26-cf27-4c17-88aa-28fb13980254")
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_IMAGE_CAPTION_LIMIT = 1024


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
        timeout: float = 30.0,
    ):
        self.gateway_url = gateway_url.rstrip("/")
        self.internal_token = internal_token
        self.gateway_channel_id = gateway_channel_id
        self.text = text
        self.media = media
        self.client = client
        self.timeout = timeout

    @staticmethod
    def idempotency_key(content: PublicationReference) -> str:
        if content.id is None:
            raise ValueError("ChannelContent must be persisted before publication")
        return str(uuid5(IDEMPOTENCY_NAMESPACE, f"channel-content:{content.id}"))

    @staticmethod
    def _render_parts(text: str, credit: str | None) -> tuple[str, str]:
        plain, rendered = render_news(text)
        if credit is not None:
            if not isinstance(credit, str) or not credit.strip():
                raise ValueError("Image credit must be non-empty text")
            # Credit is plain text. Keep it verbatim, including its whitespace.
            plain += "\n\n" + credit
            rendered += "\n\n" + escape(credit, quote=False)
        return plain, rendered

    @staticmethod
    def _fits(wire_text: str, visible_text: str, limit: int) -> bool:
        # Gateway bounds the wire string; Telegram bounds UTF-16 visible text.
        return len(wire_text) <= limit and len(visible_text.encode("utf-16-le")) // 2 <= limit

    @classmethod
    def render_html(
        cls, text: str, limit: int = TELEGRAM_TEXT_LIMIT, *, credit: str | None = None
    ) -> str:
        """Strict HTML rendering, retained for text-only publications and callers."""
        plain, rendered = cls._render_parts(text, credit)
        if not cls._fits(rendered, plain, limit):
            raise ValueError(f"Complete publication exceeds the {limit}-character Telegram budget")
        return rendered

    @classmethod
    def prepare_publication(
        cls, text: str, media: PublicationMedia | None = None
    ) -> tuple[str, str | None]:
        """Prepare a caption without rewriting facts or mutating stored content."""
        if media is None:
            return cls.render_html(text, TELEGRAM_TEXT_LIMIT), "HTML"
        plain, rendered = cls._render_parts(text, media.credit)
        if cls._fits(rendered, plain, TELEGRAM_IMAGE_CAPTION_LIMIT):
            return rendered, "HTML"
        if cls._fits(plain, plain, TELEGRAM_IMAGE_CAPTION_LIMIT):
            return plain, None
        # Only redundant ASCII spacing and extra blank lines may be removed.
        # Keep every non-empty line, sentence and paragraph in its original order.
        compact = "\n".join(
            re.sub(r"[ \t]+", " ", line).strip(" \t")
            for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        )
        compact = re.sub(r"\n{3,}", "\n\n", compact).strip()
        plain, _ = cls._render_parts(compact, media.credit)
        if cls._fits(plain, plain, TELEGRAM_IMAGE_CAPTION_LIMIT):
            return plain, None
        raise ValueError(
            f"Complete publication exceeds the {TELEGRAM_IMAGE_CAPTION_LIMIT}-character Telegram budget"
        )

    def publish(self, content: PublicationReference) -> PublishResult:
        url = f"{self.gateway_url}/api/v1/telegram/publications"
        headers = {
            "Authorization": f"Bearer {self.internal_token}",
            "Idempotency-Key": self.idempotency_key(content),
            "X-Request-ID": str(uuid4()),
        }
        try:
            formatted_text, parse_mode = self.prepare_publication(self.text, self.media)
        except ValueError as exc:
            return PublishResult(
                success=False,
                outcome="failed",
                error_code="publication_not_ready",
                error=str(exc),
            )
        payload = {
            "gateway_channel_id": self.gateway_channel_id,
            "text": formatted_text,
            "parse_mode": parse_mode,
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
        except (httpx.PoolTimeout, httpx.ConnectTimeout, httpx.ConnectError) as exc:
            return PublishResult(
                success=False, outcome="failed", error_code={
                    httpx.PoolTimeout: "gateway_pool_timeout",
                    httpx.ConnectTimeout: "gateway_connect_timeout",
                }.get(type(exc), "gateway_not_connected"),
                error="AI Gateway connection was not established",
            )
        except httpx.TransportError as exc:
            return PublishResult(
                success=False, outcome="unknown", error_code={
                    httpx.ReadTimeout: "gateway_read_timeout",
                    httpx.WriteTimeout: "gateway_write_timeout",
                    httpx.ReadError: "gateway_read_error",
                    httpx.WriteError: "gateway_write_error",
                    httpx.RemoteProtocolError: "gateway_protocol_error",
                }.get(type(exc), "gateway_transport_unknown"),
                error="AI Gateway delivery outcome is unknown after a transport failure",
            )

        retry_after_at = self._retry_after(response.headers.get("Retry-After"))
        if response.status_code != 200:
            # 409 can refer to an already-published operation; 5xx can follow a send.
            error = f"AI Gateway returned HTTP {response.status_code}"
            try:
                data = response.json()
                details = json.dumps(data, ensure_ascii=False)
            except ValueError:
                data = None
                details = response.text
            rejected = (
                response.status_code in {401, 403, 404, 422, 429}
                and isinstance(data, dict)
                and isinstance(data.get("detail"), (str, list))
                and not any(key in data for key in (
                    "external_message_id", "status", "provider", "channel_id",
                ))
            )
            if details:
                error += f": {details}"
            if response.headers.get("Retry-After"):
                error += f" (Retry-After: {response.headers['Retry-After']})"
            return PublishResult(
                success=False, outcome="failed" if rejected else "unknown",
                error_code="gateway_rejected" if rejected else "gateway_response_unknown",
                gateway_http_status=response.status_code, error=error,
                retry_after_at=retry_after_at,
            )

        try:
            data = response.json()
        except ValueError:
            data = None
        if not (
            isinstance(data, dict)
            and data.get("status") == "published"
            and data.get("provider") == "telegram"
            and data.get("channel_id") == self.gateway_channel_id
            and type(data.get("external_message_id")) is int
            and data["external_message_id"] > 0
        ):
            return PublishResult(
                success=False, outcome="unknown", error_code="gateway_invalid_response",
                gateway_http_status=200,
                error="AI Gateway returned an invalid publication response",
            )
        external_message_id = data["external_message_id"]

        published_at = datetime.now(timezone.utc)
        date_header = response.headers.get("Date")
        if date_header:
            try:
                parsed = parsedate_to_datetime(date_header)
                if parsed.tzinfo is not None:
                    published_at = parsed.astimezone(timezone.utc)
            except (TypeError, ValueError):
                pass

        return PublishResult(
            success=True, outcome="published", gateway_http_status=200,
            platform_post_id=str(external_message_id),
            published_at=published_at,
        )

    @staticmethod
    def _retry_after(value: str | None) -> datetime | None:
        if value is None:
            return None
        try:
            if value.strip().isdigit():
                return datetime.now(timezone.utc) + timedelta(seconds=int(value.strip()))
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                return None
            return parsed.astimezone(timezone.utc)
        except (ValueError, TypeError, OverflowError):
            return None
