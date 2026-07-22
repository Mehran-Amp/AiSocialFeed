import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import Column, Integer, select
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer)

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        for i in range(10):
            session.add(User(telegram_id=i))
        await session.commit()

        # Test original code behavior
        q = select(User.telegram_id)
        stream = await session.stream(q.execution_options(yield_per=5))
        async for partition in stream.scalars().partitions(5):
            print(partition)

    await engine.dispose()

asyncio.run(main())
