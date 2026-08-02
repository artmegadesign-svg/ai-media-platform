from typing import Optional

from pydantic import BaseModel


class PostCreate(BaseModel):
    topic: str


class PostResponse(BaseModel):
    id: int
    title: str
    topic: str
    status: str

    ru_content: str
    en_content: str

    quality_score: Optional[int] = None
    quality_approved: Optional[bool] = None
    quality_issues: Optional[str] = None

    generation_source: Optional[str] = None

    class Config:
        from_attributes = True
