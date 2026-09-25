# Side imports
from fastapi import APIRouter

# Project imports
from walletscanner.routes.v1 import v1_router


router = APIRouter(prefix="/api")
router.include_router(v1_router)