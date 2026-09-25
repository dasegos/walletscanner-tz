# Side imports
from fastapi import Depends
from typing import Annotated
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import ssl

# Project imports
from walletscanner.database.postgres.models import Base
from walletscanner.core.config import settings


ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False 
ssl_context.verify_mode = ssl.CERT_NONE
engine = create_async_engine(url=settings.postgres.REMOTE_URL, echo=False, connect_args={"ssl" : ssl_context}, pool_recycle=1800, pool_pre_ping=True)
# engine = create_async_engine(url=settings.postgres.URL, echo=False)
session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

async def get_session():
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            raise e

SessionDep = Annotated[AsyncSession, Depends(get_session)]


# For debugging purposes
# Automatic database creation 
async def create_database():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        await conn.run_sync(Base.metadata.create_all)
        
# Automatic database deletion 
async def drop_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
