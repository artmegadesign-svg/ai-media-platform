from sqlalchemy.orm import Session

from db.session import SessionLocal
from models.post import Post
from services.media.planning_service import MediaPlanningService


def _post(db: Session) -> Post:
    post = Post(title="Plan", topic="media", ru_content="Текст", en_content="Text")
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def test_generated_plan_creates_one_pending_neutral_asset():
    with SessionLocal() as db:
        post = _post(db)
        asset = MediaPlanningService(db).plan(post.id, None)

        assert asset.source == "generated"
        assert asset.url == "media://pending/generate_image"
        assert asset.metadata_["planning_status"] == "generation_required"
        assert asset.metadata_["language_code"] is None
        assert len(post.media_assets) == 1


def test_official_plan_stores_reference_without_downloading():
    with SessionLocal() as db:
        post = _post(db)
        provenance = {"release_id": "42"}
        url = "https://organization.example/releases/diagram.png"
        asset = MediaPlanningService(db).plan(
            post.id,
            {
                "news_type": "official_release",
                "material_type": "diagram",
                "verified_official_source": True,
                "source_url": url,
                "official_domain": "organization.example",
                "origin": "official_press_office",
                "license_type": "official_publication",
                "provenance": provenance,
            },
        )

        assert asset.url == url
        assert asset.origin == "official_press_office"
        assert asset.license_type == "official_publication"
        assert asset.metadata_["provenance"] == provenance
        assert asset.metadata_["planning_status"] == "reference_ready"
