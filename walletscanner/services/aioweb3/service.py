# Side imports
from web3 import AsyncWeb3
from web3.constants import ADDRESS_ZERO
from eth_abi import encode
from eth_utils import crypto
from fastapi import Depends
from typing import Any, Annotated
from decimal import Decimal
import asyncio

# Project imports
from walletscanner.database.redis.crud import RedisTasksService
from walletscanner.database.postgres.enums import TransactionType, AssetType
from walletscanner.services.aioweb3.constants import CONTRACTS, pUSDTopics, CTFTopics
from walletscanner.core.dependencies import get_async_web3_session
from walletscanner.core.logger import app_logger
from walletscanner.core.exceptions import WalletAddressInvalidError, RPC_ERRORS


class AsyncWeb3Client:
    """
    The class that implements methods for retrieving 
    Polymarket wallet history and balance.
    """
    PUSD_CONTRACT_ADDRESS = CONTRACTS.get("pusd").get("address")
    CONDITIONAL_TOKENS_ADDRESS = CONTRACTS.get("conditional_tokens").get("address")

    def __init__(self, 
        web3_client: Annotated[AsyncWeb3, Depends(get_async_web3_session)],
        redis_service: Annotated[RedisTasksService, Depends()]
    ) -> None:
        
        self.web3_client = web3_client
        self.redis_service = redis_service

        self.PUSD_CONTRACT = self.web3_client.eth.contract(address=self.PUSD_CONTRACT_ADDRESS, abi=CONTRACTS.get("pusd").get("abi"))
        self.CONDITIONAL_TOKENS_CONTRACT = self.web3_client.eth.contract(address=self.CONDITIONAL_TOKENS_ADDRESS, abi=CONTRACTS.get("conditional_tokens").get("abi"))

    def _calculate_lost_token_asset_id(self, condition_id: str, outcome_index_mask: int) -> Decimal:
        """
        This method recovers the asset ID of the lost tokens.
        Uses the algorithm specified in the official documentation.

        :param condition_id: Unique hex of the market.
        :type condition_id: str 
        :param outcome_index_mask: Mask of the outcome index.
        :type outcome_index_mask: int

        :return: Restored token asset_id (position_id) on Polymarket.
        :rtype: Decimal
        """
        # Each outcome token has a unique position ID, which is 
        # used as its ERC-1155 token ID. CTF computes it onchain in 
        # three steps:
        # 1) Compute the Condition ID;
        # 2) Compute the Collection IDs;
        # 3) Compute the Position IDs.
        # source: https://docs.polymarket.com/trading/positions/how-positions-work

        parent_collection_id = bytes(32)
        condition_id = bytes.fromhex(condition_id.replace("0x", ""))
        
        # function getCollectionId(bytes32 parentCollectionId, 
        #                          bytes32 conditionId, 
        #                          uint indexSet) 
        # internal view returns (bytes32)
        encoded_collection = encode(
            ["bytes32", "bytes32", "uint256"], 
            [parent_collection_id, condition_id, outcome_index_mask]
        )
        collection_id = crypto.keccak(encoded_collection)
        collateral_token = CONTRACTS.get("pusd").get("address")

        # function getPositionId(IERC20 collateralToken, 
        #                        bytes32 collectionId) 
        # internal pure returns (uint)
        # IERC20 == address
        encoded_position = encode(
            ["address", "bytes32"], 
            [collateral_token, collection_id]
        )
        position_id = crypto.keccak(encoded_position)

        asset_id = Decimal(int.from_bytes(position_id, byteorder="big"))
        return asset_id
    

    async def _process_log(self, log: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        """
        The method converts a raw log entry into a format accepted by the database 
        for storage. It analyzes the sender and recipient of funds to determine the transaction 
        type and the nature of the transferred assets, and extracts the transfer 
        amounts using the contract ABIs.
        
        :param log: unprocessed event log.
        :type log: dict[str, Any]

        :return: a single processed log or a list of them.
        :rtype: dict[str, Any] | list[dict[str, Any]]
        """
        processed_log = {
            "transaction_hash": log["transactionHash"].hex(),
            "log_index": log["logIndex"],
            "block_number": log["blockNumber"]
        }

        event_signature = "0x" + log["topics"][0].hex()

        # TRANSFER EVENTS
        if event_signature == pUSDTopics.TRANSFER.value:
            # event Transfer(address indexed from, address indexed to, uint256 value);
            # from - 1, to - 2
            decoded_log = self.PUSD_CONTRACT.events.Transfer().process_log(log)
            processed_log["asset_type"] = AssetType.USDT
            processed_log["asset_id"] = None
            from_address = decoded_log["args"]["from"]
            to_address = decoded_log["args"]["to"]
            processed_log["from_address"] = from_address
            processed_log["to_address"] = to_address
            processed_log["amount"] = decoded_log["args"]["amount"]
            
            if from_address == ADDRESS_ZERO and to_address != ADDRESS_ZERO:
                processed_log["transaction_type"] = TransactionType.DEPOSIT
            elif from_address != ADDRESS_ZERO and to_address == ADDRESS_ZERO:
                processed_log["transaction_type"] = TransactionType.WITHDRAW
            else:
                processed_log["transaction_type"] = TransactionType.TRADE

            return processed_log
    
        # TRANSFER SINGLE/BATCH EVENTS
        else:
            # event TransferSingle(address indexed operator, address indexed from, address indexed to, uint256 id, uint256 value);
            # event TransferBatch(address indexed operator, address indexed from, address indexed to, uint256[] ids, uint256[] values);
            # from - 2, to - 3
            lost_tokens_ids = list()
            
            processed_log["asset_type"] = AssetType.SHARE
            from_address = "0x" + log["topics"][2].hex()[-40:]
            to_address = "0x" + log["topics"][3].hex()[-40:]
            processed_log["from_address"] = from_address
            processed_log["to_address"] = to_address

            if from_address == ADDRESS_ZERO and to_address != ADDRESS_ZERO:
                processed_log["transaction_type"] = TransactionType.SPLIT
            elif from_address != ADDRESS_ZERO and to_address == ADDRESS_ZERO:
                # It is either Merge or Redeem
                # Fetching all logs on this transaction and trying to find events we need
                receipt = await self.web3_client.eth.get_transaction_receipt(log["transactionHash"].hex())
                receipt_logs = receipt.get("logs")

                for transaction_log in receipt_logs:
                    _log_event_signature = "0x" + transaction_log["topics"][0].hex()
                    
                    if _log_event_signature == CTFTopics.POSITIONS_MERGE.value:
                        processed_log["transaction_type"] = TransactionType.MERGE
                        break  

                    elif _log_event_signature == CTFTopics.PAYOUT_REDEMPTION.value:
                        processed_log["transaction_type"] = TransactionType.REDEEM
                        decoded_log = self.CONDITIONAL_TOKENS_CONTRACT.events.PayoutRedemption().process_log(transaction_log)
                        args = decoded_log["args"]
                        condition_id = args["conditionId"].hex()
                        lost_tokens_ids = [
                            str(self._calculate_lost_token_asset_id(condition_id, mask))
                            for mask in args.get("indexSets", [])
                        ]
                        break
                
            else:
                processed_log["transaction_type"] = TransactionType.TRADE

            # TRANSFER SINGLE EVENT
            if event_signature == CTFTopics.TRANSFER_SINGLE.value:
                decoded_log = self.CONDITIONAL_TOKENS_CONTRACT.events.TransferSingle().process_log(log)["args"]
                if lost_tokens_ids:
                    raw_log_args = dict()
                    raw_log_args["lost_asset_ids"] = lost_tokens_ids
                    processed_log["raw_log_args"] = raw_log_args
                processed_log["asset_id"] = decoded_log["id"]
                processed_log["amount"] = decoded_log["value"]
                return processed_log

            # TRANSFER BATCH EVENT
            else:
                decoded_log = self.CONDITIONAL_TOKENS_CONTRACT.events.TransferBatch().process_log(log)["args"]
                if lost_tokens_ids:
                    raw_log_args = dict()
                    raw_log_args["lost_asset_ids"] = lost_tokens_ids
                    processed_log["raw_log_args"] = raw_log_args
                asset_ids = decoded_log["ids"]
                amounts = decoded_log["values"]
                batch_transactions = list()
                for i in range(len(asset_ids)):
                    batch_transactions.append(
                        {**processed_log, "asset_id": asset_ids[i], "amount": amounts[i]}
                    )
                return batch_transactions
            

    async def _worker_fetch_chunk(self, 
        queue: asyncio.Queue, 
        wallet_topic_address: str, 
        progress_bar_data: dict[str, Any],
        logs_list: list[Any],
        min_chunk: int = 1000,
    ) -> None:
        """
        Worker. It takes a task from the queue; if there are no tasks, 
        it waits indefinitely for them to arrive. It terminates upon receiving 
        the value `None` (Poison Pill pattern). It processes all log entries 
        within the assigned range and updates the "global" `logs_list` list, 
        which is shared among all workers.
        
        :param queue: task queue (shared among all workers).
        :type queue: asyncio.Queue
        :param wallet_topic_address: wallet address, (!) must be chechsum already.
        :type wallet_topic_address: str
        :param progress_bar_data: progress bar to monitor changes.
        :type progress_bar_data: dict[str, Any]
        :param logs_list: list for storing processed logs (shared among all workers).
        :type logs_list: list[Any]
        :param min_chunk: the minimum chunk size to which we can split it.
        :type min_chunk: int

        :return: None.
        :rtype: None
        """
        redis_wallet_key = "0x" + wallet_topic_address[-40:].lower()

        while True:
            task = await queue.get() 
            
            if task is None:
                queue.task_done()
                break
                
            start_block, end_block = task

            logs_filters = [
                # pUSD
                {"address": self.PUSD_CONTRACT_ADDRESS, "topics": [pUSDTopics.TRANSFER.value, None, wallet_topic_address]}, # in-Transfers
                {"address": self.PUSD_CONTRACT_ADDRESS, "topics": [pUSDTopics.TRANSFER.value, wallet_topic_address, None]}, # out-Transfers

                # Conditional Tokens
                {"address": self.CONDITIONAL_TOKENS_ADDRESS, "topics": [CTFTopics.TRANSFER_SINGLE.value, None, None, wallet_topic_address]}, # in-SingleTransfers
                {"address": self.CONDITIONAL_TOKENS_ADDRESS, "topics": [CTFTopics.TRANSFER_SINGLE.value, None, wallet_topic_address, None]}, # out-SingleTransfers

                {"address": self.CONDITIONAL_TOKENS_ADDRESS, "topics": [CTFTopics.TRANSFER_BATCH.value, None, None, wallet_topic_address]}, # in-BatchTransfers
                {"address": self.CONDITIONAL_TOKENS_ADDRESS, "topics": [CTFTopics.TRANSFER_BATCH.value, None, wallet_topic_address, None]}, # out-BatchTransfers
            ]

            for log_filter in logs_filters:
                log_filter["fromBlock"] = start_block
                log_filter["toBlock"] = end_block

            try:
                tasks = [self.web3_client.eth.get_logs(f) for f in logs_filters]
                chunk_results = await asyncio.gather(*tasks, return_exceptions=False)

                for result in chunk_results:
                    for log in result:
                        result = await self._process_log(log)
                        if isinstance(result, dict):
                            logs_list.append(result) 
                        else: 
                            logs_list.extend(result) 

                progress_bar_data["processed"] += (end_block - start_block + 1)
                app_logger.info(f"PROGRESS: {progress_bar_data["processed"]} / {progress_bar_data["total"]} ({progress_bar_data["processed"]/progress_bar_data["total"]*100}%) blocks scanned.")

                await self.redis_service.refresh_ttl(redis_wallet_key)

                queue.task_done()

            except Exception as e:
                app_logger.error(f"ERROR OCCURED: {e}")
                error_str = str(e).lower()
                error_code = None
                
                if hasattr(e, "rpc_response") and isinstance(e.rpc_response, dict):
                    error_code = e.rpc_response.get("error", {}).get("code")

                if "429" in error_str or "timeout" in error_str or error_code == RPC_ERRORS.CONN_TIMEOUT_ERROR or "413" in error_str or "payload too large" in error_str:
                    if (end_block - start_block) < min_chunk: 
                        # The problem is not the chunk being too heavy. We don't split it, but just go to asyncio.sleep()

                        app_logger.error(f"TOO MANY REQUESTS with minimum chunk size reached: sleeping for 5.0 seconds.") 

                        await asyncio.sleep(5.0)
                        await queue.put((start_block, end_block)) 

                    else:
                        # Splitting the chunk on the recommendation of web3.py:
                        # "In the case of eth_getLogs, the JSON-RPC call gives a timeout 
                        # error, decrease the end block number and tries again with a 
                        # smaller block range window."
                        # source: https://web3py.readthedocs.io/en/stable/filters.html

                        mid = start_block + (end_block - start_block) // 2

                        app_logger.info(f"HEAVY BLOCK: splitting the chunk {start_block}-{end_block} into two pieces: {start_block}-{mid} & {mid+1}-{end_block}") 

                        await queue.put((start_block, mid))
                        await queue.put((mid + 1, end_block))

                elif error_code == RPC_ERRORS.BLOCK_UNFINALIZED_ERROR:
                    app_logger.warning(f"BLOCK NOT FINALIZED: sleeping for 5.0 seconds.")
                    await asyncio.sleep(5.0)
                    await queue.put((start_block, end_block))
                    queue.task_done() 

                else:
                    raise e
                    
            finally:
                await asyncio.sleep(0.1) # Finally sleeping for some more time so that we don't catch the Timeout again

    async def retrieve_history(self, 
        address: str, 
        chunk_size: int = 10000,
        workers_amount: int = 20,
    ) -> list[dict[str, Any]]:
        """
        The method for retrieving the full transaction history for a wallet address. 
        It obtains the wallet's creation date and the current latest block, spawns 
        workers and assigns them tasks to collect blockchain logs, and subsequently 
        calls a method to process those logs.

        :param address: wallet address.
        :type address: str
        :param chunk_size: range of blocks to scan in a single task. 
        :type chunk_size: int 
        :param workers_amount: amount of workers to complete tasks.
        :type workers_amount: int

        :return: processed logs.
        :rtype: list[dict[str, Any]]
        """
        try:
            wallet_checksum_address = self.web3_client.to_checksum_address(address)
        except ValueError:
            raise WalletAddressInvalidError(address)

        last_block = await self.web3_client.eth.block_number - 5 # last block in blockchain (finalized)
        start_block = await self.get_wallet_creation_block(wallet_checksum_address) # the block in which the wallet was created
        wallet_topic_address = self.transform_address_for_topic(wallet_checksum_address)

        progress_bar_data = {"processed": 0, "total": last_block - start_block + 1}

        queue = asyncio.Queue()

        while start_block <= last_block:
            end_block = min(start_block + chunk_size - 1, last_block)
            await queue.put((start_block, end_block))
            start_block = end_block + 1

        logs_list = list()

        # Creating workers themselves and assigning them tasks
        workers = [
            asyncio.create_task(self._worker_fetch_chunk(queue, wallet_topic_address, progress_bar_data, logs_list))
            for _ in range(workers_amount)
        ]

        # Waiting for the queue to run out of tasks
        await queue.join()

        # We use `queue.get()`` method inside of `while True` loop,
        # hence this we need to manually stop all workers by sending 
        # a pre-prepared message. (Poison Pill pattern).
        # [NOTE] we are doing this inside of an infinite 
        # loop with queue.get(), because otherwise data loss in possible
        for _ in range(workers_amount):
            await queue.put(None)

        # [IMPORTANT!] To avoid "Unawaited Tasks Leak"
        await asyncio.gather(*workers)

        app_logger.info(f"|FINISH| Retrieved {len(logs_list)} logs")
        return logs_list
        
    async def get_wallet_creation_block(self, address: str) -> int:
        """
        The method retrieves the number of the block in which the proxy-address was created.
        The underlying logic is as follows: prior to the creation of the Polymarket wallet, this 
        blockchain address was empty. The moment the Polymarket factory created the wallet, the 
        smart contract bytecode appeared there permanently. A binary search algorithm is used.

        :param address: Polymarket wallet address.
        :type address: str
        :return: Number of the block in which the proxy-address was created.
        :rtype: int
        """
        try:
            wallet_checksum_address = self.web3_client.to_checksum_address(address)
        except ValueError:
            raise WalletAddressInvalidError(address)

        left = 0
        right = await self.web3_client.eth.block_number
        deployment_block = None
        while left <= right:
            mid = (left + right) // 2
            if await self.web3_client.eth.get_code(wallet_checksum_address, block_identifier=mid) != b"":
                deployment_block = mid
                right = mid - 1 
            else:
                left = mid + 1  

        return deployment_block

    async def get_balance(self, address: str) -> Decimal:
        """
        The method retrieves the current Polymarket wallet balance (in pUSD).

        :param address: Polymarket wallet address.
        :type address: str
        :return: Current wallet balance.
        :rtype: int
        """
        try:
            wallet_checksum_address = self.web3_client.to_checksum_address(address)
        except ValueError:
            raise WalletAddressInvalidError(address)
        
        raw_balance = await self.PUSD_CONTRACT.functions.balanceOf(wallet_checksum_address).call()
        decimals = await self.PUSD_CONTRACT.functions.decimals().call()
        balance = Decimal(raw_balance) / (Decimal(10) ** decimals)
        return balance
    
    def transform_address_for_topic(self, address: str) -> str:
        """
        The method converts the address into a format accepted by the blockchain 
        in the topics field. It removes spaces, converts the address to lowercase, 
        and pads the address (minus the prefix) with leading zeros to a length 
        of 64 characters.

        :param address: Polymarket wallet address.
        :type address: str
        :return: transformed address.
        :rtype: str
        """
        result = "0x" + address.strip().lower().replace("0x", "").zfill(64)
        return result
