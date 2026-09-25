# Side imports
from fastapi import APIRouter

# Project imports
from walletscanner.routes.v1.wallets import router as wallets_router


v1_router = APIRouter(prefix="/v1")
v1_router.include_router(wallets_router)