# Side imports
from fastapi import APIRouter, Depends
from typing import Annotated
from sqlalchemy import and_

# Project imports
from walletscanner.schemas.schemas import(PUSDBalanceSchema, BlockNumberSchema, 
                                          UserWalletSchema, HistorySchema,
                                          TransactionsCounts,
                                          SortingParams,
                                          FilteringUserBalancesParams, FilteringTransactionsParams
                                          )
from walletscanner.database.postgres.crud import TransactionsService, CoinBalanceService
from walletscanner.services.aioweb3.service import AsyncWeb3Client
from walletscanner.services.aioweb3.pipeline import ServicePipeline


router = APIRouter(prefix="/wallets")


@router.get(
    "/{address}/current_pusd_balance",
    summary="Get pUSD wallet balance",
    description="Fetches the exact on-chain pUSD balance directly from the smart contract using the `balanceOf` method."
)
async def get_current_pusd_balance(
    address: str,
    service: Annotated[AsyncWeb3Client, Depends()]
):
    balance = await service.get_balance(address)
    return PUSDBalanceSchema(balance=balance)


@router.get(
    "/{address}/creation_block",
    summary="Get wallet creation block",
    description="Locates the exact deployment block of the proxy wallet using the `get_code` method and a binary search algorithm."
)
async def get_creation_block(
    address: str,
    web3_service: Annotated[AsyncWeb3Client, Depends()]
):
    block = await web3_service.get_wallet_creation_block(address)
    return BlockNumberSchema(block_number=block)


@router.get(
    "/{address}/balance",
    summary="Get tracked token balances",
    description=(
        "Returns the full list of parsed asset balances (pUSD and Conditional Tokens) from the database. Supports pagination and filtering.\n\n"
        "**Note:** Returns `{\"status\": \"pending\"}` if the blockchain indexing pipeline is still running."
    )
)
async def get_full_balance(
    address: str,
    balances_service: Annotated[CoinBalanceService, Depends()],
    service_pipeline: Annotated[ServicePipeline, Depends()],
    sorting_query: SortingParams = Depends(),
    filtering_query: FilteringUserBalancesParams = Depends()
):
    data = await service_pipeline.resolve_data(address)
    if data.get("status") == "pending":
        return data
    else:
        sorting_query = sorting_query.model_dump()
        filtering_query = filtering_query.model_dump(exclude_none=True)
        
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
    

@router.get(
    "/{address}/history",
    summary="Get transactions history",
    description=(
        "Retrieves parsed transaction history from the database since the wallet's creation block. Supports pagination and filtering.\n\n"
        "**Note:** Returns `{\"status\": \"pending\"}` if the blockchain indexing pipeline is still running."
    )
)
async def get_history(
    address: str,
    transactions_service: Annotated[TransactionsService, Depends()],
    service_pipeline: Annotated[ServicePipeline, Depends()],
    sorting_query: SortingParams = Depends(),
    filtering_query: FilteringTransactionsParams = Depends()
):
    data = await service_pipeline.resolve_data(address)
    if data.get("status") == "pending":
        return data
    else:
        sorting_query = sorting_query.model_dump()
        filtering_query = filtering_query.model_dump(exclude_none=True)

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
    

@router.get(
    "/{address}/transactions/counts",
    summary="Get number of transactions of different types",
    description=(
        "Returns the total number of transactions grouped by transaction type (`TRADE`, `DEPOSIT`, `WITHDRAW`, etc.) from the database.\n\n"
        "**Note:** Returns `{\"status\": \"pending\"}` if the blockchain indexing pipeline is still running."
    )
)
async def get_transactions_counts(
    address: str,
    service_pipeline: Annotated[ServicePipeline, Depends()],
    transactions_service: Annotated[TransactionsService, Depends()]
):  
    data = await service_pipeline.resolve_data(address)
    if data.get("status") == "pending":
        return data
    else:
        expr_func = lambda m: (m.from_address == address) | (m.to_address == address),
        result = await transactions_service.count_by("id", group_by="transaction_type", expr_func=expr_func)
        return TransactionsCounts(counts=dict(result))