from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MediaAssetResponse(BaseModel):
    id: int
    post_id: int
    type: str
    source: str
    origin: str
    license_type: str
    url: str
    thumbnail_url: str | None
    metadata: dict[str, Any] | None = Field(validation_alias="metadata_")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
