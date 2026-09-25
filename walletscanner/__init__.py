# Side imports
from fastapi import FastAPI
from contextlib import asynccontextmanager

# Project imports
from walletscanner.routes import router as base_router
from walletscanner.core.config import settings
from walletscanner.core.dependencies import get_async_web3_session, get_async_redis_client
from walletscanner.database.postgres.engine import create_database, drop_database
from walletscanner.routes.v1.exc import wallet_address_invalid_error, invalid_filtering_params_exc
from walletscanner.core.exceptions import WalletAddressInvalidError, InvalidFilteringParamsException


@asynccontextmanager
async def lifespan(app: FastAPI):

    await get_async_web3_session()
    session = await get_async_redis_client()
    await create_database()

    yield
    # await drop_database() # for debugging purposes
    async with session:
        await session.flushdb()


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
    app.add_exception_handler(InvalidFilteringParamsException, invalid_filtering_params_exc)

    return app
