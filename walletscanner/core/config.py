# Side imports
import os
from dotenv import load_dotenv


load_dotenv()


class PostgresDBConfig:
    PORT       : int = int(os.getenv("POSTGRES_PORT", "5432"))
    HOST       : str = os.getenv("POSTGRES_HOST")
    DATABASE   : str = os.getenv("POSTGRES_DATABASE")
    USERNAME   : str = os.getenv("POSTGRES_USERNAME")
    PASSWORD   : str = os.getenv("POSTGRES_PASSWORD")
    URL        : str = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
    REMOTE_URL : str = os.getenv("POSTGRES_REMOTE_URL")


class RedisDBConfig:
    PORT       : str = os.getenv("REDIS_PORT")
    HOST       : str = os.getenv("REDIS_HOST")
    USERNAME   : str = os.getenv("REDIS_USERNAME")
    PASSWORD   : str = os.getenv("REDIS_PASSWORD")
    REMOTE_URL : str = f"rediss://{USERNAME}:{PASSWORD}@{HOST}:{PORT}"    


class Settings:
    postgres : PostgresDBConfig = PostgresDBConfig()
    redis    : RedisDBConfig    = RedisDBConfig()
    RPC_URL  : str              = "https://tenderly.rpc.polygon.community"
    DEBUG    : bool             = False


settings = Settings()