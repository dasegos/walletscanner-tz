# Side imports
from redis.asyncio import Redis as AioRedis
from fastapi import Depends
from typing import Annotated, Any

# Project imports
from walletscanner.core.dependencies import get_async_redis_client


class _RedisCRUDService:
    """
    The class for interacting with the Redis database.
    """
    SECONDS_BEFORE_EXPIRE = 0
    PREFIXES: list[str] = list()

    def __init__(self, client: Annotated[AioRedis, Depends(get_async_redis_client)]) -> None:
        self.client = client

    @property
    def prefixes_path(self):
        path = ":".join(self.PREFIXES)+":"
        return path

    async def add_hashset(self, key: str, mapping: dict[str, Any]) -> None:
        """
        The method adds a hashset to the database.

        :param key: hashset name.
        :type key: str
        :param mapping: hashset value.
        :type mapping: dict[str, Any]

        :return: None
        :rtype: None
        """
        full_key = self.prefixes_path + key.lower()
        async with self.client as session:
            await session.hset(full_key, mapping=mapping)
            await session.expire(full_key, self.SECONDS_BEFORE_EXPIRE)

    async def get_hashset(self, key: str) -> dict[str, Any]:
        """
        The method retrieves some hashset from the database.

        :param key: hashset name.
        :type key: str

        :return: hashset value.
        :rtype: dict[str, Any]
        """
        full_key = self.prefixes_path + key.lower()
        async with self.client as session:
            result = await session.hgetall(full_key)
            return result

    async def delete_hashset(self, key: str) -> None:
        """
        The method deletes some hashset from the database.

        :param key: hashset name.
        :type key: str 
        
        :return: None
        :rtype: None
        """
        full_key = self.prefixes_path + key
        async with self.client as session:
            await session.delete(full_key)
  
    async def refresh_ttl(self, key: str) -> None:
        """
        The method extends the lifespan of the key.

        :param key: hashset name.
        :type key: str 
        
        :return: None
        :rtype: None
        """
        return await self.client.expire(name=key, time=self.SECONDS_BEFORE_EXPIRE)
    

class RedisTasksService(_RedisCRUDService):
    SECONDS_BEFORE_EXPIRE = 500
    prefixes = ["wallets"]