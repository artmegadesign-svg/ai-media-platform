from sqlalchemy import select
from db.session import SessionLocal
from models.language import Language


async def seed_languages():
    async with SessionLocal() as session:
        result = await session.execute(select(Language))
        existing = result.scalars().all()

        if existing:
            return

        session.add_all([
            Language(code="ru", name="Russian"),
            Language(code="en", name="English"),
        ])

        await session.commit()
