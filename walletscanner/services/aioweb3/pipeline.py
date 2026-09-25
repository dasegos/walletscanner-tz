# Side imports
from fastapi import Depends, BackgroundTasks
from typing import Any, Annotated

# Project imports
from walletscanner.services.aioweb3.constants import CONTRACTS
from walletscanner.database.postgres.crud import TransactionsService, CoinBalanceService
from walletscanner.database.postgres.enums import TransactionType, AssetType
from walletscanner.database.redis.crud import RedisTasksService
from walletscanner.services.aioweb3.service import AsyncWeb3Client
from walletscanner.core.logger import app_logger



class ServicePipeline:
    """
    The pipeline class that manages database 
    records and the retrieval of transaction history.
    """
    def __init__(
        self,
        redis_service: Annotated[RedisTasksService, Depends()],
        web3_service: Annotated[AsyncWeb3Client, Depends()],
        transactions_service: Annotated[TransactionsService, Depends()],
        balances_service: Annotated[CoinBalanceService, Depends()],
        background_tasks: BackgroundTasks
    ) -> None:
        self.redis_service = redis_service
        self.web3_service = web3_service
        self.transactions_service = transactions_service
        self.balances_service = balances_service
        self.background_tasks = background_tasks


    async def _run_pipeline(self, address: str) -> None:
        """
        The method that implements a background task.
        Launches the methods to retrieve history and 
        calculate balances, then adds all transactions 
        and active balances to the database. 

        :param address: wallet address.
        :type address: str

        :return: None.
        :rtype: None
        """
        try:
            processed_logs = await self.web3_service.retrieve_history(address)
            await self.transactions_service.add_many(processed_logs)
            pusd_balance = await self.transactions_service.calculate_pusd_balance(address)
            active_token_balances = await self.transactions_service.calculate_token_balances(address)
            
            balances_to_add = [
                {"wallet_address": address, "asset_type": AssetType.USDT, "asset_id": None, "amount": pusd_balance}
            ]
            token_balances_dicts = [{"wallet_address": address, "asset_type": AssetType.SHARE, "asset_id": item[0], "amount": item[1]} for item in active_token_balances]
            balances_to_add.extend(token_balances_dicts)
            await self.balances_service.add_many(balances_to_add)

            app_logger.info(f"Wallet data successfully retrieved and recorded in the database.")
            
        except Exception as e:
            app_logger.error(f"Critical wallet pipeline failure ({address}): {e}")
            raise e
            
        finally:
            await self.redis_service.delete_hashset(address)

    async def resolve_missing_data(self, address: str) -> dict[str, Any]:
        """
        The method to resolve data is it's missing.
        Searches for a corresponding key in Redis database.
        If does not find one, launches a background task to 
        collect transaction history.

        :param address: wallet address.
        :type address: str

        :return: status message (pending).
        :rtype: dict[str, Any]
        """
        task = await self.redis_service.get_hashset(address)
        mapping = {"address": address, "status": "pending"}
        if not task:
            app_logger.info("KEY NOT FOUND! Adding a background task to process.")
            await self.redis_service.add_hashset(address, mapping)
            self.background_tasks.add_task(self._run_pipeline, address)
        return mapping