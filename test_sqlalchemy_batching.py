import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import Column, Integer
from sqlalchemy.orm import declarative_base
from sqlalchemy import select

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

        q = select(User.telegram_id)
        # Using stream and partitions
        stream = await session.stream(q.execution_options(yield_per=5))
        async for partition in stream.scalars().partitions(5):
            print("Partition:", partition)

        print("Done partitions")

asyncio.run(main())
