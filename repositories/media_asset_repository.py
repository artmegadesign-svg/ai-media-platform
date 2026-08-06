from sqlalchemy.orm import Session

from models.media_asset import MediaAsset
from repositories.base import BaseRepository


class MediaAssetRepository(BaseRepository[MediaAsset]):
    def __init__(self, db: Session):
        super().__init__(db=db, model=MediaAsset)

    def get_by_post(self, post_id: int) -> list[MediaAsset]:
        return (
            self.db.query(MediaAsset)
            .filter(MediaAsset.post_id == post_id)
            .order_by(MediaAsset.created_at.asc(), MediaAsset.id.asc())
            .all()
        )

    def get(self, asset_id: int) -> MediaAsset | None:
        return self.get_by_id(asset_id)

    def delete(self, asset_id: int) -> MediaAsset | None:
        asset = self.get(asset_id)
        if asset is None:
            return None
        self.db.delete(asset)
        self.db.commit()
        return asset
