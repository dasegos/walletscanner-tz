# Side imports
from web3 import AsyncWeb3, AsyncHTTPProvider
from redis.asyncio import Redis as AioRedis

# Project imports
from walletscanner.core.config import settings


_async_web3_session: AsyncWeb3 | None = None
_async_redis_client: AioRedis | None = None


async def get_async_web3_session() -> AsyncWeb3:
    global _async_web3_session
    if _async_web3_session is None:
        _async_web3_session = AsyncWeb3(AsyncHTTPProvider(settings.RPC_URL))
    return _async_web3_session


async def get_async_redis_client() -> AioRedis:
    global _async_redis_client
    if _async_redis_client is None:
        _async_redis_client = AioRedis(host=settings.redis.HOST, port=settings.redis.PORT, password=settings.redis.PASSWORD, db=0)
    return _async_redis_client