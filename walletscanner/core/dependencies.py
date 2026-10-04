# Side imports
from fastapi import Depends
from web3 import AsyncWeb3, AsyncHTTPProvider
from redis.asyncio import Redis as AioRedis
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

# Project imports
from walletscanner.core.config import settings
from walletscanner.database.postgres.engine import get_session


_async_web3_session: AsyncWeb3 | None = None
_async_redis_client: AioRedis | None = None
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_async_web3_session() -> AsyncWeb3:
    global _async_web3_session
    if _async_web3_session is None:
        _async_web3_session = AsyncWeb3(AsyncHTTPProvider(settings.RPC_URL))
    return _async_web3_session

async def get_async_redis_client() -> AioRedis:
    global _async_redis_client
    if _async_redis_client is None:
        _async_redis_client = AioRedis.from_url(
            settings.redis.LOCAL_URL,
            decode_responses=True,
            db=0)
    return _async_redis_client

async def close_connections():
    global _async_web3_session, _async_redis_client
    
    if _async_redis_client is not None:
        await _async_redis_client.aclose()
        _async_redis_client = None
        
    if _async_web3_session is not None:
        if hasattr(_async_web3_session.provider, "disconnect"):
            await _async_web3_session.provider.disconnect()
        _async_web3_session = None