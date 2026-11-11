from datetime import datetime, timezone
from uuid import uuid4
from typing import Literal

from pydantic import BaseModel, Field


class ImageUsage(BaseModel):
    """Reviewed permission for one exact image, never inferred from ownership."""

    license_type: str = Field(min_length=1)
    terms_url: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    usage_allowed: bool = False
    attribution_required: bool = False
    attribution: str | None = None


class OfficialImagePolicy(BaseModel):
    # Exact hosts, including explicitly approved CDN hosts. No wildcard trust.
    image_hosts: list[str] = Field(default_factory=list)
    permissions: dict[str, ImageUsage] = Field(default_factory=dict)


class OfficialImageCandidate(BaseModel):
    url: str
    page_url: str
    source: str
    discovery_method: str
    official_hosts: list[str]
    usage: ImageUsage | None = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NewsItem(BaseModel):
    """A provider-independent representation of a news story."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    title: str
    url: str
    content: str | None = None
    published_at: datetime | None = None
    image_url: str | None = None
    official_images: list[OfficialImageCandidate] = Field(default_factory=list)
    image_discovery_status: Literal["not_checked", "complete", "temporary_error"] = (
        "not_checked"
    )
    image_discovery_error: str | None = None
    category: str = "other"
    score: int = Field(default=0, ge=0, le=100)
