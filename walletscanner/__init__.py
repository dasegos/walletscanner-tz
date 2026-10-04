# Side imports
from fastapi import FastAPI
from contextlib import asynccontextmanager

# Project imports
from walletscanner.routes import router as base_router
from walletscanner.core.config import settings
from walletscanner.core.dependencies import get_async_redis_client, close_connections
from walletscanner.database.postgres.engine import create_database, drop_database
from walletscanner.routes.v1.exc import wallet_address_invalid_error, wallet_not_initialized_error, invalid_filtering_params_exc
from walletscanner.core.exceptions import WalletAddressInvalidError, WalletNotInitializedError, InvalidFilteringParamsException


@asynccontextmanager
async def lifespan(app: FastAPI):

    # Not initializing Web3 and Redis manually - they will be created lazily on their own
    await create_database()

    yield
    
    try:
        if settings.DEBUG:
            if settings.DROP_DATABASE:
                await drop_database() 
            redis_client = await get_async_redis_client()
            await redis_client.flushdb()
    finally:
        await close_connections()


def create_app() -> FastAPI:

    app = FastAPI(
        title="Wallet Scanner",
        description="The app to retrieve Polymarket wallet balances and transactions.",
        version="0.1.0",
        debug=settings.DEBUG,
        lifespan=lifespan
    )

    app.include_router(base_router)
    app.add_exception_handler(WalletAddressInvalidError, wallet_address_invalid_error)
    app.add_exception_handler(WalletNotInitializedError, wallet_not_initialized_error)
    app.add_exception_handler(InvalidFilteringParamsException, invalid_filtering_params_exc)

    return app
