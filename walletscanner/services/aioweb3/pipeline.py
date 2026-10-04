# Side imports
from fastapi import Depends, BackgroundTasks
from typing import Any, Annotated
import uuid

# Project imports
from walletscanner.core.dependencies import SessionDep
from walletscanner.database.postgres.crud import TransactionsService, CoinBalanceService, ScanStateService
from walletscanner.database.postgres.enums import AssetType, ScanStatus
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
        session: SessionDep,
        redis_service: Annotated[RedisTasksService, Depends()],
        web3_service: Annotated[AsyncWeb3Client, Depends()],
        transactions_service: Annotated[TransactionsService, Depends()],
        balances_service: Annotated[CoinBalanceService, Depends()],
        scan_states_service: Annotated[ScanStateService, Depends()],
        background_tasks: BackgroundTasks
    ) -> None:
        self.session = session
        self.redis_service = redis_service
        self.web3_service = web3_service
        self.transactions_service = transactions_service
        self.balances_service = balances_service
        self.scan_states_service = scan_states_service
        self.background_tasks = background_tasks


    async def _run_pipeline(self, address: str, start_block: int, lock_token: str) -> None:
        """
        Executes the background wallet scraping and balance calculation pipeline.
        Retrieves blockchain event history, stores transactions, computes current asset 
        balances, and atomicly flushes state updates into the database. Guarantees 
        lock release upon completion or unexpected failure.

        :param address: wallet address.
        :type address: str
        :param lock_token: unique value of the redis lock.
        :type lock_token: str

        :return: None.
        :rtype: None
        """
        try: 
            processed_logs = await self.web3_service.retrieve_history(address, start_block)
            # await self.transactions_service.add_many(processed_logs) # Not for much data, is slow
            await self.transactions_service.add_many_raw(processed_logs) # For extra speed when ping is to big

            pusd_balance = await self.transactions_service.calculate_pusd_balance(address)
            active_token_balances = await self.transactions_service.calculate_token_balances(address)
            balances_to_add = [
                {"wallet_address": address, "asset_type": AssetType.PUSD, "asset_id": None, "amount": pusd_balance},
                *(
                    {"wallet_address": address, "asset_type": AssetType.SHARE, "asset_id": asset_id, "amount": amount}
                    for asset_id, amount in active_token_balances
                ),
            ]

            await self.balances_service.upsert(update_cols=["amount"], instances=balances_to_add, commit=False)
            await self.scan_states_service.upsert(
                update_cols=["status", "error_message", "updated_at"],
                wallet_address=address,
                status=ScanStatus.SUCCESS,
                error_message=None,
                commit=False
            )
            await self.session.commit()

            app_logger.info(f"Wallet {address}: scan completed successfully.")

        except Exception as e:
            app_logger.error(f"Critical wallet pipeline failure ({address}): {e}")
            await self.session.rollback()
            await self.scan_states_service.upsert(
                update_cols=["status", "error_message", "updated_at"],
                wallet_address=address,
                status=ScanStatus.FAILED,
                error_message=str(e),
            )
            raise

        finally:
            await self.redis_service.release_set_safe(address, lock_token)


    async def resolve_data(self, address: str) -> dict[str, Any]:
        """
        Resolves the indexing task state and dispatches background workers.

        Checks active Redis locks and historical Postgres states to immediately return 
        cached data. If data is missing or stale, atomically acquires a task lock and 
        spawns a new isolated background pipeline thread.
        
        :param address: wallet address.
        :type address: str

        :return: status message (pending).
        :rtype: dict[str, Any]
        """
        address = address.lower()
        task = await self.redis_service.is_active(address)
        if task:
            app_logger.debug("Background task is already running.")
            return {"status" : "pending"}
        task_state = await self.scan_states_service.get_one_by_pk(address)
        if task_state and task_state.status == ScanStatus.SUCCESS:
            return {"status" : "success"}   
        wallet_addess_data = await self.web3_service.validate_wallet_address(address) # wallet address validation
        token = str(uuid.uuid4())
        acquired = await self.redis_service.set_atomically(address, token)
        if acquired:
            self.background_tasks.add_task(self._run_pipeline, address, wallet_addess_data[1], token)
            app_logger.debug("Background task launched!")
        return {"status" : "pending"}