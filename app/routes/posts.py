from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.post import PostCreate, PostResponse
from schemas.media_asset import MediaAssetResponse
from services.ai_engine.services.generator_service import GeneratorService
from services.ai_engine.services.post_service import PostService
from services.media.service import MediaService


router = APIRouter(
    prefix="/posts",
    tags=["posts"],
)


@router.get("/{post_id}/media", response_model=list[MediaAssetResponse])
def get_post_media(post_id: int, db: Session = Depends(get_db)):
    return MediaService(db).list_post_assets(post_id)


@router.get("", response_model=list[PostResponse])
async def get_posts(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
):
    return PostService().get_latest(limit=limit, offset=offset)


@router.post("", response_model=PostResponse)
async def create_post(data: PostCreate):

    topic = data.topic.strip()

    if not topic:
        raise HTTPException(
            status_code=400,
            detail="Topic is required",
        )

    try:
        result = GeneratorService().generate(topic)

        if result.get("status") == "rejected":
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Content rejected by quality control",
                    "quality_score": result.get("quality_score"),
                    "quality_approved": False,
                    "quality_issues": result.get(
                        "quality_issues",
                        result.get("issues", []),
                    ),
                },
            )

        return result

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=str(error),
        )
