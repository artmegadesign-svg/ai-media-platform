from fastapi import FastAPI

from core.settings import settings

from app.routes.posts import router as posts_router
from app.routes.channels import router as channels_router
from app.routes.channel_contents import router as channel_contents_router
from app.routes.publish import router as publish_router
from app.routes.analytics import router as analytics_router


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
)


app.include_router(posts_router)
app.include_router(channels_router)
app.include_router(channel_contents_router)
app.include_router(publish_router)
app.include_router(analytics_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
