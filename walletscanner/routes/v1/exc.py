# Side imports
from fastapi import Request, status
from fastapi.responses import JSONResponse

# Project imports
from walletscanner.core.exceptions import WalletAddressInvalidError, WalletNotInitializedError, InvalidFilteringParamsException


def wallet_address_invalid_error(request: Request, exc: WalletAddressInvalidError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"message" : str(exc)}
    )


def wallet_not_initialized_error(request: Request, exc: WalletNotInitializedError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"message" : str(exc)}
    )


def invalid_filtering_params_exc(request: Request, exc: InvalidFilteringParamsException):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"message" : str(exc)}
    )