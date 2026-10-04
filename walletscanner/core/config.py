# Side imports
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field


ENV_DEVELOPMENT_FILE_PATH = Path(__file__).resolve().parent / "settings" / ".env.development"
ENV_DEPLOYMENT_FILE_PATH = Path(__file__).resolve().parent / "settings" / ".env.deployment"


class ConfigBase(BaseSettings): 
    model_config = SettingsConfigDict( 
        env_file=ENV_DEVELOPMENT_FILE_PATH, 
        env_file_encoding="utf-8", 
        extra="ignore" 
    )
    

class PostgresDBConfig(ConfigBase): 
    model_config = SettingsConfigDict(env_prefix="POSTGRES_") 

    LOCAL_PORT     : int 
    LOCAL_HOST     : str 
    LOCAL_DATABASE : str 
    LOCAL_USERNAME : SecretStr 
    LOCAL_PASSWORD : SecretStr 
    
    @property
    def LOCAL_URL(self) -> str: 
        return f"postgresql+asyncpg://{self.LOCAL_USERNAME.get_secret_value()}:{self.LOCAL_PASSWORD.get_secret_value()}@{self.LOCAL_HOST}:{self.LOCAL_PORT}/{self.LOCAL_DATABASE}"
    
    # REMOTE SETTINGS TO ADD IF NECESSARY
    # ...


class RedisDBConfig(ConfigBase): 
    model_config = SettingsConfigDict(env_prefix="REDIS_") 

    LOCAL_PORT     : str 
    LOCAL_HOST     : str 
    LOCAL_PASSWORD : SecretStr 

    @property 
    def LOCAL_URL(self) -> str: 
        return f"redis://:{self.LOCAL_PASSWORD.get_secret_value()}@{self.LOCAL_HOST}:{self.LOCAL_PORT}/0" 

    # REMOTE SETTINGS TO ADD IF NECESSARY
    # ...


class Settings(ConfigBase): 
    postgres      : PostgresDBConfig = Field(default_factory=PostgresDBConfig) 
    redis         : RedisDBConfig    = Field(default_factory=RedisDBConfig) 
    RPC_URL       : str              = "https://tenderly.rpc.polygon.community"
    DEBUG         : bool             = True
    DROP_DATABASE : bool             = False
    

settings = Settings()