# Side imports
from enum import Enum


class ServiceException(Exception):
    pass


class PostgresDBException(ServiceException):
    pass


class InstanceNotFoundException(PostgresDBException):
    def __str__(self) -> str:
        return "Instance not found!"
    

class InvalidFilteringParamsException(PostgresDBException):
    def __init__(self, msg: str) -> None:
        self.msg = msg

    def __str__(self) -> str:
        return f"Invalid filtering params passed: {self.msg}"


class BlockchainException(ServiceException):
    pass


class WalletAddressInvalidError(BlockchainException):
    def __init__(self, address) -> None:
        self.address = address

    def __str__(self) -> str:
        return f"Passed wallet address is invalid: {self.address}"
    

class RPC_ERRORS(int, Enum):
    BLOCK_UNFINALIZED_ERROR = -32603
    BLOCK_NOT_FOUND_ERROR   = -32001
    CONN_TIMEOUT_ERROR      = -32000