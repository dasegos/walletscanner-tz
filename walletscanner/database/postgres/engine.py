# Side imports
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Project imports
from walletscanner.database.postgres.models import Base
from walletscanner.core.config import settings


# engine = create_async_engine(url=settings.postgres.REMOTE_URL, echo=False) # remote engine
engine = create_async_engine(url=settings.postgres.LOCAL_URL, echo=False) # local engine
session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

async def get_session():
    async with session_maker() as session:
        yield session

# Automatic database creation 
async def create_database():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        await conn.run_sync(Base.metadata.create_all)
        
# For debugging purposes
# Automatic database deletion 
async def drop_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
