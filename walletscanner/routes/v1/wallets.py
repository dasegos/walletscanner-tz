# Side imports
from fastapi import APIRouter, Depends
from typing import Annotated
from sqlalchemy import and_

# Project imports
from walletscanner.schemas.schemas import(pUSDBalanceSchema, BlockNumberSchema, 
                                          UserWalletSchema, HistorySchema,
                                          SortingParams,
                                          FilteringUserBalancesParams, FilteringTransactionsParams
                                          )
from walletscanner.database.postgres.crud import TransactionsService, CoinBalanceService
from walletscanner.services.aioweb3.service import AsyncWeb3Client
from walletscanner.services.aioweb3.pipeline import ServicePipeline


router = APIRouter(prefix="/wallets")


@router.get(
    "/{address}/current_pusd_balance",
    summary="Get pUSD Polymarket wallet balance",
    description="Retrieves the exact Polymarket wallet balance in pUSD using the `balanceOf` method (Extra)."
)
async def get_current_pusd_balance(
    address: str,
    service: Annotated[AsyncWeb3Client, Depends()]
):
    balance = await service.get_balance(address)
    return pUSDBalanceSchema(balance=balance)


@router.get(
    "/{address}/creation_block",
    summary="Get Polymarket wallet creation block",
    description="Retrieves the block in which the Polymarket wallet was created, using the `get_code` method and a binary search algorithm."
)
async def get_creation_block(
    address: str,
    web3_service: Annotated[AsyncWeb3Client, Depends()]
):
    block = await web3_service.get_wallet_creation_block(address)
    return BlockNumberSchema(block_number=block)


@router.get(
    "/{address}/balance",
    summary="Get full list of Polymarket wallet balances",
    description="Returns the full list of Polymarket wallet balances (pUSD and Conditional Tokens) by retrieving the history of all transactions performed since the wallet's creation date. Supports filtering."
)
async def get_full_balance(
    address: str,
    balances_service: Annotated[CoinBalanceService, Depends()],
    service_pipeline: Annotated[ServicePipeline, Depends()],
    sorting_query: SortingParams = Depends(),
    filtering_query: FilteringUserBalancesParams = Depends()
):
    sorting_query = sorting_query.model_dump()
    filtering_query = filtering_query.model_dump(exclude_none=True)

    expr_func_exist = lambda m: m.wallet_address == address
    balances_exist = await balances_service.exists(expr_func=expr_func_exist)

    if balances_exist:
        expr_func_balance= lambda m: and_(
            (m.wallet_address == address),
            *[getattr(m, key) == val for key, val in filtering_query.items()]
        )
        balances = await balances_service.get_many(
            order_by=sorting_query.get("sort_by"),
            sort_order=sorting_query.get("sort_order"),
            page=sorting_query.get("page"),
            per_page=sorting_query.get("per_page"),
            expr_func=expr_func_balance
        )
        return UserWalletSchema(wallet_address=address, balances=balances)
    
    else:
        data = await service_pipeline.resolve_missing_data(address)
        return data

@router.get(
    "/{address}/history",
    summary="Get full list of Polymarket wallet transactions",
    description="Retrieves the history of all transactions performed since the wallet's creation date. Supports filtering."
)
async def get_history(
    address: str,
    transactions_service: Annotated[TransactionsService, Depends()],
    service_pipeline: Annotated[ServicePipeline, Depends()],
    sorting_query: SortingParams = Depends(),
    filtering_query: FilteringTransactionsParams = Depends()
):
    sorting_query = sorting_query.model_dump()
    filtering_query = filtering_query.model_dump(exclude_none=True)

    expr_func_exist = lambda m: (m.from_address == address) | (m.to_address == address)
    transactions_exist = await transactions_service.exists(expr_func=expr_func_exist)

    if transactions_exist:
        expr_func_transactions = lambda m: and_(
            (m.from_address == address) | (m.to_address == address),
            *[getattr(m, key) == val for key, val in filtering_query.items()]
        )

        transactions = await transactions_service.get_many(
            order_by=sorting_query.get("sort_by"),
            sort_order=sorting_query.get("sort_order"),
            page=sorting_query.get("page"),
            per_page=sorting_query.get("per_page"),
            expr_func=expr_func_transactions
        )
        return HistorySchema(transactions=transactions)
    
    else:
        data = await service_pipeline.resolve_missing_data(address)
        return data