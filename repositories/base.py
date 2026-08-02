from typing import Generic, Type, TypeVar

from sqlalchemy.orm import Session

from db.base import Base


ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    def __init__(
        self,
        db: Session,
        model: Type[ModelType],
    ):
        self.db = db
        self.model = model

    def get_by_id(self, object_id: int):
        return (
            self.db.query(self.model)
            .filter(self.model.id == object_id)
            .first()
        )

    def get_all(self):
        return self.db.query(self.model).all()

    def create(self, obj: ModelType):
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, obj: ModelType):
        self.db.delete(obj)
        self.db.commit()
        return obj
