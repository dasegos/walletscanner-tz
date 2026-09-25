# Side imports
from datetime import datetime
from decimal import Decimal
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Project imports
from walletscanner.database.postgres.enums import AssetType, TransactionType


class BlockNumberSchema(BaseModel):
    block_number : int


class pUSDBalanceSchema(BaseModel):
    balance : Decimal


class CoinBalanceSchema(BaseModel):
    id               : int
    asset_type       : AssetType
    asset_id         : Decimal | None
    amount           : Decimal
    updated_at       : datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def validate_amount_field(self):
        if self.asset_type == AssetType.USDT:
            self.amount /= (10 ** 6)
        else:
            self.amount /= (10 ** 18)
        return self


class UserWalletSchema(BaseModel):
    wallet_address : str
    amount         : int | None              = None
    balances       : list[CoinBalanceSchema]

    @model_validator(mode="after")
    def validate_amount_field(self):
        self.amount = len(self.balances)
        return self


class TransactionSchema(BaseModel):
    id               : int
    from_address     : str 
    to_address       : str
    transaction_type : TransactionType
    asset_type       : AssetType
    asset_id         : Decimal | None
    amount           : Decimal
    transaction_hash : str
    log_index        : int
    block_number     : int
    # raw_log_args     : dict | None # For debugging purposes

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def validate_amount_field(self):
        if self.asset_type == AssetType.USDT:
            self.amount /= (10 ** 6)
        else:
            self.amount /= (10 ** 18)
        return self


class HistorySchema(BaseModel):
    amount       : int                     = None
    transactions : list[TransactionSchema] = list()

    @model_validator(mode="after")
    def validate_amount_field(self):
        self.amount = len(self.transactions)
        return self
    

class SortingParams(BaseModel):
    page       : int                    = Field(gt=0, default=1)
    per_page   : int | None             = Field(gt=0, default=100)
    sort_by    : str                    = "id"
    sort_order : Literal["asc", "desc"] = "asc"


class FilteringTransactionsParams(BaseModel):
    transaction_type : TransactionType | None = None
    asset_type       : AssetType | None       = None
    asset_id         : Decimal | None         = None
    block_number     : int | None             = None     


class FilteringUserBalancesParams(BaseModel):
    asset_type : AssetType | None       = None
    asset_id   : Decimal | None         = None  