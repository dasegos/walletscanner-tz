# Side imports
from redis.asyncio import Redis as AioRedis
from fastapi import Depends
from abc import abstractmethod, ABC
from typing import Annotated, Any

# Project imports
from walletscanner.core.dependencies import get_async_redis_client


class _RedisCRUDService(ABC):
    """
    The class for interacting with the Redis database.
    """
    SECONDS_BEFORE_EXPIRE = 0

    def __init__(self, client: Annotated[AioRedis, Depends(get_async_redis_client)]) -> None:
        self.client = client

    @property
    @abstractmethod
    def PREFIXES(self) -> tuple[str, ...]:
        """Each subclass is required to define its own namespace."""
        pass

    @property
    def prefixes_path(self):
        if not self.PREFIXES:
            return ""
        return ":".join(self.PREFIXES)+":"
    
    def _full_key(self, key: str): 
        return self.prefixes_path + key.lower()
    
    # LUA SCRIPTS
    # ------------------------------------------------------------
    # Atomic test-and-delete Lua script guaranteeing that a worker only deletes 
    # a lock key if it still owns the specific unique value token.
    _RELEASE_SCRIPT = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        else
            return 0
        end
    """
    # ------------------------------------------------------------

    async def set_atomically(self, key: str, value: Any) -> bool:
        """
        The method creates a set atomically only if 
        one has not been created yet.

        :param key: set name.
        :type key: str 
        :param value: set value.
        :type value: Any 

        :return: if set has been created.
        :rtype: bool
        """
        full_key = self._full_key(key)
        expire = self.SECONDS_BEFORE_EXPIRE if self.SECONDS_BEFORE_EXPIRE > 0 else None
        result = await self.client.set(full_key, value, nx=True, ex=expire)
        return bool(result)
    
    async def release_set_safe(self, key: str, value: Any) -> bool:
        """
        The method deletes the set with the corresponding 
        key and value, so as to prevent the deletion of sets 
        required by the system.

        :param key: set name.
        :type key: str 
        :param value: set value.
        :type value: Any 

        :return: if set has been deleted.
        :rtype: bool
        """
        full_key = self._full_key(key)
        result = await self.client.eval(self._RELEASE_SCRIPT, 1, full_key, value)
        return bool(result)
    
    async def release_set(self, key: str) -> bool:
        """
        The method deletes the set with the corresponding key.

        :param key: set name.
        :type key: str 

        :return: if set has been deleted.
        :rtype: bool
        """
        full_key = self._full_key(key)
        result = await self.client.delete(full_key)
        return bool(result)

    async def is_active(self, key: str) -> bool:
        """
        The method checks whether a set 
        with the corresponding name exists.

        :param key: set name.
        :type key: str 

        :return: if set exists.
        :rtype: bool
        """
        full_key = self._full_key(key)
        return bool(await self.client.exists(full_key))

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
        full_key = self._full_key(key)
        await self.client.hset(full_key, mapping=mapping)
        if self.SECONDS_BEFORE_EXPIRE > 0:
            await self.client.expire(full_key, self.SECONDS_BEFORE_EXPIRE)

    async def get_hashset(self, key: str) -> dict[str, Any]:
        """
        The method retrieves some hashset from the database.

        :param key: hashset name.
        :type key: str

        :return: hashset value.
        :rtype: dict[str, Any]
        """
        full_key = self._full_key(key)
        result = await self.client.hgetall(full_key)
        return result

    async def delete_hashset(self, key: str) -> None:
        """
        The method deletes some hashset from the database.

        :param key: hashset name.
        :type key: str 
        
        :return: None
        :rtype: None
        """
        full_key = self._full_key(key)
        await self.client.delete(full_key)
  
    async def refresh_ttl(self, key: str) -> None:
        """
        The method extends the lifespan of the key.

        :param key: hashset name.
        :type key: str 
        
        :return: None
        :rtype: None
        """
        if self.SECONDS_BEFORE_EXPIRE > 0:
            full_key = self._full_key(key)
            await self.client.expire(name=full_key, time=self.SECONDS_BEFORE_EXPIRE)
    

class RedisTasksService(_RedisCRUDService):
    SECONDS_BEFORE_EXPIRE = 7200
    PREFIXES = ("wallets", "locks")
