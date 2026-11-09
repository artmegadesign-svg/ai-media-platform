from typing import Generic, Type, TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.base import Base


ModelType = TypeVar("ModelType", bound=Base)


def is_unique_conflict(
    error: IntegrityError, index_name: str, sqlite_columns: str,
) -> bool:
    """Recognize only the requested UNIQUE, not arbitrary integrity failures."""
    original = error.orig
    if getattr(original, "pgcode", None) == "23505":
        return getattr(getattr(original, "diag", None), "constraint_name", None) == index_name
    return (
        getattr(original, "sqlite_errorname", None) == "SQLITE_CONSTRAINT_UNIQUE"
        and str(original) == f"UNIQUE constraint failed: {sqlite_columns}"
    )


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
