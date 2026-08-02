from fastapi import APIRouter, HTTPException

from app.schemas.post import PostCreate, PostResponse
from services.ai_engine.services.generator_service import GeneratorService
from services.ai_engine.services.post_service import PostService


router = APIRouter(
    prefix="/posts",
    tags=["posts"],
)


@router.get("", response_model=list[PostResponse])
async def get_posts():
    return PostService().get_latest()


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

        saved_post = PostService().save(
            topic=topic,
            ru=result.get("ru_content", result.get("ru", "")),
            en=result.get("en_content", result.get("en", "")),
            quality_result={
                "score": result.get("quality_score"),
                "approved": result.get("quality_approved"),
                "issues": result.get("quality_issues"),
            },
        )

        return saved_post

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=str(error),
        )
