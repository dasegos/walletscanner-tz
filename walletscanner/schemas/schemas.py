# Side imports
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Any
from pydantic import BaseModel, ConfigDict, PlainSerializer, Field, model_serializer, model_validator, computed_field

# Project imports
from walletscanner.database.postgres.enums import AssetType, TransactionType


DecimalString = Annotated[
    Decimal, 
    PlainSerializer(lambda v: f"{v:f}" if isinstance(v, Decimal) else v, return_type=str)
]

def _normalize_amount(value: Any, asset_type: AssetType) -> Decimal:
    amount = Decimal(str(value))
    if asset_type == AssetType.PUSD:
        return amount / Decimal("1000000")
    return amount / Decimal("1000000000000000000") 


class BlockNumberSchema(BaseModel):
    block_number : int


class PUSDBalanceSchema(BaseModel):
    balance : Decimal


class CoinBalanceSchema(BaseModel):
    id               : int
    asset_type       : AssetType
    asset_id         : Decimal | None
    amount           : DecimalString
    updated_at       : datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def normalize_amount(self) -> "CoinBalanceSchema":
        self.amount = _normalize_amount(self.amount, self.asset_type)
        return self
    

class UserWalletSchema(BaseModel):
    wallet_address : str
    balances       : list[CoinBalanceSchema] = Field(default_factory=list)
    
    @computed_field
    def balances_count(self) -> int:
        return len(self.balances)

    @model_serializer(mode="wrap")
    def serialize_in_order(self, handler):
        default_dict = handler(self)
        ordered_dict = {
            "balances_count": self.balances_count,
            **default_dict
        }
        return ordered_dict


class TransactionSchema(BaseModel):
    id               : int
    from_address     : str 
    to_address       : str
    transaction_type : TransactionType
    asset_type       : AssetType
    asset_id         : Decimal | None
    amount           : DecimalString
    transaction_hash : str
    log_index        : int
    block_number     : int

    # raw_log_args     : dict | None # For debugging purposes

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def normalize_amount(self) -> "TransactionSchema":
        self.amount = _normalize_amount(self.amount, self.asset_type)
        return self


class HistorySchema(BaseModel):
    transactions : list[TransactionSchema] = Field(default_factory=list)

    @computed_field
    def transactions_count(self) -> int:
        return len(self.transactions)
    
    @model_serializer(mode="wrap")
    def serialize_in_order(self, handler):
        default_dict = handler(self)
        ordered_dict = {
            "transactions_count": self.transactions_count,
            **default_dict
        }
        return ordered_dict
    

class TransactionsCounts(BaseModel):
    counts : dict[TransactionType, int]


class SortingParams(BaseModel):
    page       : int | None                    = Field(gt=0, default=1)
    per_page   : int | None                    = Field(gt=0, default=100)
    sort_by    : str | None                    = "id"
    sort_order : Literal["asc", "desc"] | None = "asc"


class FilteringTransactionsParams(BaseModel):
    transaction_type : TransactionType | None = None
    asset_type       : AssetType | None       = None
    asset_id         : Decimal | None         = None
    block_number     : int | None             = None     


class FilteringUserBalancesParams(BaseModel):
    asset_type : AssetType | None = None
    asset_id   : Decimal | None   = None 