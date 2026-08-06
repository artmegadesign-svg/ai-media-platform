from sqlalchemy.orm import Session

from models.media_asset import MediaAsset
from repositories.media_asset_repository import MediaAssetRepository


class MediaService:
    def __init__(self, db: Session):
        self.repository = MediaAssetRepository(db)

    def attach_asset(self, asset: MediaAsset) -> MediaAsset:
        return self.repository.create(asset)

    def list_post_assets(self, post_id: int) -> list[MediaAsset]:
        return self.repository.get_by_post(post_id)
