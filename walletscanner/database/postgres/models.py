# Side imports
from sqlalchemy import Enum, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates
from sqlalchemy.types import CHAR, Integer, Numeric, String, DateTime
from sqlalchemy.dialects.postgresql import JSONB, CITEXT

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Annotated

# Project imports
from walletscanner.database.postgres.enums import TransactionType, AssetType, ScanStatus


intpk = Annotated[int, mapped_column(primary_key=True)]


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transactions"

    id               : Mapped[intpk]
    from_address     : Mapped[str]                    = mapped_column(CITEXT, nullable=False, index=True, unique=False)
    to_address       : Mapped[str]                    = mapped_column(CITEXT, nullable=False, index=True, unique=False)
    transaction_type : Mapped[TransactionType]        = mapped_column(Enum(TransactionType), nullable=False)
    asset_type       : Mapped[AssetType]              = mapped_column(Enum(AssetType), nullable=False)
    asset_id         : Mapped[Decimal | None]         = mapped_column(Numeric(precision=78, scale=0), nullable=True)
    amount           : Mapped[Decimal]                = mapped_column(Numeric(precision=78, scale=0), nullable=False)
    transaction_hash : Mapped[str]                    = mapped_column(CHAR(66), index=True, unique=False, nullable=False)
    log_index        : Mapped[int]                    = mapped_column(Integer, nullable=False, unique=False)
    block_number     : Mapped[int]                    = mapped_column(Integer, nullable=False, unique=False)
    raw_log_args     : Mapped[dict[str, Any] | None]  = mapped_column(JSONB, default=None, nullable=True)
    
    # Transaction uniqueness based on hash, log index within the block, and position ID (applicable to ERC-1155 Batch)
    __table_args__ = (
        Index(
            "uq_transaction_hash_log_index_asset_id",
            "transaction_hash", "log_index", "asset_id",
            unique=True,
            postgresql_nulls_not_distinct=True
        ),
    )
    
    # [WARNING] `@validates` is not executed when writing to the database through the raw connection! 
    @validates("from_address", "to_address")
    def validate_addresses_and_length(self, key: str, value: str) -> str:
        if value:
            if len(value) != 42:
                raise ValueError("The wallet address must be 42 characters long.")
            return value.lower()
        return value


class CoinBalance(Base):
    __tablename__ = "balances"

    id               : Mapped[intpk]
    wallet_address   : Mapped[str]            = mapped_column(CITEXT, nullable=False, index=True, unique=False)
    asset_type       : Mapped[AssetType]      = mapped_column(Enum(AssetType), nullable=False)
    asset_id         : Mapped[Decimal | None] = mapped_column(Numeric(precision=78, scale=0), nullable=True)
    amount           : Mapped[Decimal]        = mapped_column(Numeric(precision=78, scale=0), nullable=False)
    updated_at       : Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index(
            "uq_wallet_asset_type_asset_id",
            "wallet_address", "asset_type", "asset_id",
            unique=True,
            postgresql_nulls_not_distinct=True
        ),
    )

    # [WARNING] `@validates` is not executed when writing to the database through the raw connection! 
    @validates("wallet_address")
    def validate_addresses_and_length(self, key: str, value: str) -> str:
        if value:
            if len(value) != 42:
                raise ValueError("The wallet address must be 42 characters long.")
            return value.lower()
        return value


class ScanState(Base):
    __tablename__ = "scan_states"

    wallet_address   : Mapped[str]        = mapped_column(CITEXT, primary_key=True)
    status           : Mapped[ScanStatus] = mapped_column(Enum(ScanStatus), nullable=False)
    error_message    : Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at       : Mapped[datetime]   = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # [WARNING] `@validates` is not executed when writing to the database through the raw connection! 
    @validates("wallet_address")
    def validate_addresses_and_length(self, key: str, value: str) -> str:
        if value:
            if len(value) != 42:
                raise ValueError("The wallet address must be 42 characters long.")
            return value.lower()
        return value