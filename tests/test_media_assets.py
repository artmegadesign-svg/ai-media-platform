from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from db.session import SessionLocal
from models.media_asset import MediaAsset
from models.post import Post
from repositories.media_asset_repository import MediaAssetRepository
from services.media.service import MediaService


def _post(db: Session, topic: str = "media") -> Post:
    post = Post(
        title="Media foundation",
        topic=topic,
        ru_content="Текст",
        en_content="Text",
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def _asset(post_id: int, **overrides) -> MediaAsset:
    values = {
        "post_id": post_id,
        "type": "image",
        "source": "generated",
        "origin": "ai",
        "license_type": "generated",
        "url": "media://generated/illustration.png",
        "metadata_": {"prompt_version": "v1"},
    }
    values.update(overrides)
    return MediaAsset(**values)


def test_create_generated_media_asset():
    with SessionLocal() as db:
        post = _post(db, "generated")
        asset = MediaAssetRepository(db).create(_asset(post.id))

        assert asset.id is not None
        assert asset.type == "image"
        assert asset.source == "generated"
        assert asset.metadata_ == {"prompt_version": "v1"}


def test_attach_asset_to_post_and_retrieve_it():
    with SessionLocal() as db:
        post = _post(db, "attach")
        service = MediaService(db)
        attached = service.attach_asset(_asset(post.id))

        assert attached.post.id == post.id
        assert service.list_post_assets(post.id) == [attached]


def test_multiple_assets_per_post():
    with SessionLocal() as db:
        post = _post(db, "multiple")
        service = MediaService(db)
        service.attach_asset(_asset(post.id))
        service.attach_asset(
            _asset(
                post.id,
                type="infographic",
                url="media://generated/chart.png",
            )
        )

        assert [asset.type for asset in service.list_post_assets(post.id)] == [
            "image",
            "infographic",
        ]


def test_delete_asset():
    with SessionLocal() as db:
        post = _post(db, "delete")
        repository = MediaAssetRepository(db)
        asset = repository.create(_asset(post.id))
        asset_id = asset.id

        assert repository.delete(asset_id) is asset
        assert repository.get(asset_id) is None


def test_official_document_and_video_assets():
    with SessionLocal() as db:
        post = _post(db, "official")
        service = MediaService(db)
        document = service.attach_asset(
            _asset(
                post.id,
                type="document",
                source="official",
                origin="official_document",
                license_type="official_public",
                url="https://company.example/releases/report.pdf",
            )
        )
        video = service.attach_asset(
            _asset(
                post.id,
                type="video",
                source="official",
                origin="official_youtube",
                license_type="official_public",
                url="https://youtube.example/watch/official",
            )
        )

        assert document.source == "official"
        assert document.type == "document"
        assert video.source == "official"
        assert video.type == "video"


def test_get_post_media_endpoint():
    with SessionLocal() as db:
        post = _post(db, "endpoint")
        asset = MediaService(db).attach_asset(_asset(post.id))
        post_id = post.id
        asset_id = asset.id

    response = TestClient(app).get(f"/posts/{post_id}/media")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": asset_id,
            "post_id": post_id,
            "type": "image",
            "source": "generated",
            "origin": "ai",
            "license_type": "generated",
            "url": "media://generated/illustration.png",
            "thumbnail_url": None,
            "metadata": {"prompt_version": "v1"},
            "created_at": response.json()[0]["created_at"],
        }
    ]


def test_migration_is_registered_as_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(Config("alembic.ini"))

    assert scripts.get_heads() == ["c4d8e2f19a75"]
    assert scripts.get_revision("c4d8e2f19a75").down_revision == "a7c91e4d2f10"
